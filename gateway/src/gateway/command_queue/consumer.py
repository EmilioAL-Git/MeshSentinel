"""Consumo de comandos backend -> gateway vía Redis Streams (ADR 0003/0013).

Entrega fiable: consumer group + ACK explícito tras procesar. El consumo es
secuencial: 1 comando en vuelo por gateway (presupuesto de malla, diseño §4.4).
Para command.send_admin publica el ciclo de vida como eventos 'admin.operation'.
"""

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from gateway.transports.base import Transport

logger = logging.getLogger("gateway.commands")

PublishFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class CommandConsumer:
    def __init__(
        self, redis_url: str, stream: str, group: str, transport: Transport, publish: PublishFn
    ) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._stream = stream
        self._group = group
        self._consumer = "consumer-1"
        self._transport = transport
        self._publish = publish

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self) -> None:
        await self._ensure_group()
        logger.info("Consuming commands from %s (group=%s)", self._stream, self._group)
        while True:
            try:
                entries = await self._redis.xreadgroup(
                    self._group, self._consumer, {self._stream: ">"}, count=1, block=5000
                )
                for _, messages in entries or []:
                    for msg_id, fields in messages:
                        await self._handle(msg_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Command consumer error, retrying in 3s")
                await asyncio.sleep(3)

    async def _handle(self, msg_id: str, fields: dict[str, str]) -> None:
        try:
            command = json.loads(fields.get("data", "{}"))
            if command.get("command_type") == "command.send_admin":
                await self._handle_admin(command)
            else:
                await self._transport.send_command(command)
        except Exception:
            logger.exception("Failed processing command %s", msg_id)
        finally:
            # Siempre ACK: el reintento lo gobierna el backend (estados/backoff),
            # no la re-entrega del stream — evita dobles ejecuciones sobre LoRa.
            await self._redis.xack(self._stream, self._group, msg_id)

    async def _handle_admin(self, command: dict[str, Any]) -> None:
        payload = command.get("payload") or {}
        operation = {**payload, "target_node_id": command.get("target_node_id")}
        op_id = operation.get("operation_id")
        timeout = float(operation.get("timeout_seconds") or 120)

        await self._publish("admin.operation", {"operation_id": op_id, "state": "running"})
        try:
            result = await asyncio.wait_for(self._transport.execute_admin(operation), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("admin.op timeout id=%s (%s)", op_id, exc)
            await self._publish(
                "admin.operation",
                {"operation_id": op_id, "state": "timeout", "error": str(exc) or "timeout"},
            )
        except Exception as exc:
            logger.exception("admin.op failed id=%s", op_id)
            await self._publish(
                "admin.operation", {"operation_id": op_id, "state": "failed", "error": str(exc)}
            )
        else:
            await self._publish(
                "admin.operation", {"operation_id": op_id, "state": "succeeded", "result": result}
            )

    async def close(self) -> None:
        await self._redis.aclose()
