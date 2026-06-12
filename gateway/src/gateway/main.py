import asyncio
import logging
import signal

from gateway.command_queue.consumer import CommandConsumer
from gateway.config import get_settings
from gateway.events import EventPublisher
from gateway.transports.factory import create_transport

logger = logging.getLogger("gateway")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    publisher = EventPublisher(settings.redis_url, settings.events_channel, settings.gateway_id)
    transport = create_transport(settings, publisher.publish)
    consumer = CommandConsumer(
        settings.redis_url, settings.commands_stream, settings.commands_consumer_group, transport
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def heartbeat() -> None:
        # Permite al backend detectar pasarelas caídas por ausencia de latido
        while True:
            await asyncio.sleep(settings.status_interval_seconds)
            await transport.emit_status()

    tasks = [
        asyncio.create_task(transport.run(), name="transport"),
        asyncio.create_task(consumer.run(), name="commands"),
        asyncio.create_task(heartbeat(), name="heartbeat"),
    ]
    logger.info("Gateway %s started (transport=%s)", settings.gateway_id, settings.transport)

    await stop.wait()
    logger.info("Shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await transport.close()
    await consumer.close()
    await publisher.close()


if __name__ == "__main__":
    asyncio.run(main())
