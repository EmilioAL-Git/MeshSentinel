"""Encolado de comandos backend -> gateway vía Redis Streams (ADR 0003).

Persistente: los comandos sobreviven a reinicios del gateway y se entregan con
consumer group + ACK en el lado gateway.
"""

import json
from typing import Any

import redis.asyncio as aioredis


class RedisCommandQueue:
    def __init__(self, redis_url: str, stream_prefix: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._prefix = stream_prefix

    async def enqueue(self, gateway_id: str, envelope: dict[str, Any]) -> None:
        await self._redis.xadd(f"{self._prefix}{gateway_id}", {"data": json.dumps(envelope)})

    async def close(self) -> None:
        await self._redis.aclose()
