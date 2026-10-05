import asyncio
import logging
import signal
import sys

from gateway.command_queue.consumer import CommandConsumer
from gateway.config import get_settings
from gateway.events import EventPublisher
from gateway.transport_manager import TransportManager

logger = logging.getLogger("gateway")


async def main() -> int:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    publisher = EventPublisher(settings.redis_url, settings.events_channel, settings.gateway_id)
    manager = TransportManager(settings, publisher.publish)
    consumer = CommandConsumer(
        settings.redis_url,
        settings.commands_stream,
        settings.commands_consumer_group,
        manager,
        publisher.publish,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    exit_code = 0

    def fatal(reason: str) -> None:
        # Red de seguridad de proceso: un gateway medio muerto (heartbeat vivo
        # pero sin consumir comandos) es peor que uno reiniciado. Salida != 0
        # para que la política de reinicio de Docker lo levante limpio.
        nonlocal exit_code
        if not stop.is_set():
            exit_code = 1
            logger.critical("fatal: %s — shutting down", reason)
            stop.set()

    def on_loop_exception(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        # Tareas fire-and-forget sin dueño que fallan: solo se registran con
        # contexto completo (matar el proceso por un comando suelto que falla
        # sería peor que el fallo); las tareas críticas tienen su propio
        # vigilante más abajo.
        exc = context.get("exception")
        logger.error(
            "unhandled asyncio error: %s", context.get("message"),
            exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
        )

    loop.set_exception_handler(on_loop_exception)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def heartbeat() -> None:
        # Permite al backend detectar pasarelas caídas por ausencia de latido.
        # Sin el try/except, cualquier fallo transitorio en emit_status()
        # (p. ej. un hipo de Redis) mataba esta tarea para siempre en
        # silencio — asyncio no la reinicia ni lo notifica salvo que alguien
        # recoja su excepción, cosa que aquí nadie hacía hasta el shutdown.
        # Efecto observado repetidamente: un repuesto de la piscina (M6.3)
        # dejaba de latir tras un fallo puntual y solo volvía reiniciando el
        # contenedor a mano.
        while True:
            await asyncio.sleep(settings.status_interval_seconds)
            try:
                if manager.transport is not None:
                    # Sondear ANTES de emitir: el latido lleva el sello de la
                    # última respuesta real del nodo, no solo "proceso vivo".
                    await manager.transport.probe()
                    await manager.transport.emit_status()
            except Exception:
                logger.exception("heartbeat.emit_failed")

    tasks = [
        asyncio.create_task(manager.start_from_env(), name="transport-bootstrap"),
        asyncio.create_task(consumer.run(), name="commands"),
        asyncio.create_task(heartbeat(), name="heartbeat"),
    ]
    def watch_critical(task: asyncio.Task) -> None:
        if task.cancelled() or stop.is_set():
            return
        exc = task.exception()
        fatal(f"critical task {task.get_name()!r} ended" + (f": {exc!r}" if exc else " unexpectedly"))

    for task in tasks[1:]:  # commands + heartbeat nunca terminan solas
        task.add_done_callback(watch_critical)
    logger.info("Gateway %s started (transport=%s)", settings.gateway_id, settings.transport)

    await stop.wait()
    logger.info("Shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await manager.teardown()
    await consumer.close()
    await publisher.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
