import json
import logging
import time
from typing import Any, Optional

import redis.asyncio as redis
from config import REDIS_URL

logger = logging.getLogger(__name__)

# Global Redis connection pool
redis_client: Optional[redis.Redis] = None
local_cache: dict[str, tuple[float, str]] = {}


def user_financial_cache_keys(user_id: int) -> tuple[str, ...]:
    return (
        f"dashboard:{user_id}",
        f"dashboard_overview:{user_id}",
        f"insights:{user_id}",
    )

async def init_redis():
    """Initialise the global Redis connection pool."""
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        try:
            await redis_client.ping()
            logger.info("✅ Connected to Redis successfully.")
        except Exception as e:
            logger.error(f"⚠️  Could not connect to Redis: {e}")
            redis_client = None

async def close_redis():
    """Close the global Redis connection pool."""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None

async def get_cache(key: str) -> Optional[Any]:
    """Fetch and decode a JSON payload from Redis by key."""
    if redis_client is None:
        return _get_local_cache(key)
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Redis GET error for key {key}: {e}")
    return _get_local_cache(key)

async def set_cache(key: str, data: Any, ttl: int = 300) -> bool:
    """Encode a JSON payload and store it in Redis with an expiration TTL (seconds)."""
    payload = json.dumps(data)
    local_cache[key] = (time.monotonic() + ttl, payload)
    if redis_client is None:
        return True
    try:
        await redis_client.setex(key, ttl, payload)
        return True
    except Exception as e:
        logger.error(f"Redis SET error for key {key}: {e}")
        return True

async def invalidate_cache(*keys: str) -> None:
    """Delete one or more keys from Redis to invalidate stale data."""
    if not keys:
        return
    for key in keys:
        local_cache.pop(key, None)
    if redis_client is None:
        return
    try:
        await redis_client.delete(*keys)
    except Exception as e:
        logger.error(f"Redis DELETE error for keys {keys}: {e}")


def _get_local_cache(key: str) -> Optional[Any]:
    entry = local_cache.get(key)
    if not entry:
        return None

    expires_at, payload = entry
    if expires_at <= time.monotonic():
        local_cache.pop(key, None)
        return None

    try:
        return json.loads(payload)
    except Exception:
        local_cache.pop(key, None)
        return None
