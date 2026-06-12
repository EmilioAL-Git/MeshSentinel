"""Construcción y publicación de eventos conforme a shared/events/v1."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("gateway.events")

SCHEMA_VERSION = 1


def make_envelope(event_type: str, gateway_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


class EventPublisher:
    def __init__(self, redis_url: str, channel: str, gateway_id: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._channel = channel
        self._gateway_id = gateway_id

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = make_envelope(event_type, self._gateway_id, payload)
        await self._redis.publish(self._channel, json.dumps(envelope))
        logger.debug("Published %s", event_type)

    async def close(self) -> None:
        await self._redis.aclose()
