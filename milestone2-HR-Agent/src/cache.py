from __future__ import annotations

import json
import logging
from typing import Any

import redis


logger = logging.getLogger(__name__)


class ResilientCache:
    def __init__(self, redis_url: str) -> None:
        self.client = redis.Redis.from_url(
            redis_url,
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
            health_check_interval=30,
        )

    def health(self) -> bool:
        try:
            return bool(self.client.ping())
        except (redis.exceptions.RedisError, OSError):
            return False

    def get(self, key: str) -> Any | None:
        try:
            payload = self.client.get(key)
            if payload is None:
                return None
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            return json.loads(payload)
        except (redis.exceptions.RedisError, OSError, UnicodeDecodeError, TypeError, ValueError):
            logger.warning("cache get failed; continuing with cache miss")
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            self.client.setex(key, ttl_seconds, payload)
        except (redis.exceptions.RedisError, OSError, TypeError, ValueError):
            logger.warning("cache set failed; continuing without cache")


class NullCache(ResilientCache):
    def __init__(self) -> None:
        self.client = None

    def health(self) -> bool:
        return False

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        return None
