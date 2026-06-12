import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

logger = logging.getLogger("noc.events")

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RedisEventBus:
    """Suscriptor del canal de eventos del gateway y fan-out a handlers locales.

    Los eventos pub/sub son fire-and-forget (ADR 0003): la persistencia la hacen
    los handlers, nunca se asume re-entrega.
    """

    def __init__(self, redis_url: str, channel: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._channel = channel
        self._handlers: list[EventHandler] = []
        self._task: asyncio.Task[None] | None = None

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen(), name="redis-event-listener")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._redis.aclose()

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(self._channel)
                logger.info("Subscribed to %s", self._channel)
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    await self._dispatch(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Event listener error, retrying in 3s")
                await asyncio.sleep(3)

    async def _dispatch(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Discarding non-JSON event")
            return
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception("Handler failed for event %s", event.get("event_type"))
