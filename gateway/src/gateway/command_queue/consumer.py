"""Consumo de comandos backend -> gateway vía Redis Streams (ADR 0003).

Entrega fiable: consumer group + ACK explícito tras ejecutar el comando.
El rate limiting LoRa se añadirá en Fase 4 junto a los transportes reales.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from gateway.transports.base import Transport

logger = logging.getLogger("gateway.commands")


class CommandConsumer:
    def __init__(self, redis_url: str, stream: str, group: str, transport: Transport) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._stream = stream
        self._group = group
        self._consumer = "consumer-1"
        self._transport = transport

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
            await self._transport.send_command(command)
            await self._redis.xack(self._stream, self._group, msg_id)
        except Exception:
            # Sin ACK: queda pendiente en el stream para reintento/inspección
            logger.exception("Failed command %s", msg_id)

    async def close(self) -> None:
        await self._redis.aclose()
