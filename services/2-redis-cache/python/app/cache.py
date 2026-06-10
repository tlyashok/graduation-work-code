"""
Кэш рекомендаций в Redis (итерация 2, §2.5).

Стратегия - ленивая загрузка (cache-aside): при попадании в кэш
возвращается сериализованный результат; при промахе - алгоритм
вычисляет результат, сохраняет его в кэш с TTL и возвращает.

Ключи:
    recommendations:{user_id}:n={n}  - результат /recommendations/{user_id}?n=...
    popular:{user_id}:n={n}          - результат /recommendations/{user_id}/popular?n=...

TTL - единый, задаётся CACHE_TTL_SECONDS (по умолчанию 60 секунд).
"""
from __future__ import annotations

import json

import redis.asyncio as redis
from prometheus_client import Counter

from app.config import REDIS_URL, CACHE_TTL_SECONDS

CACHE_HITS = Counter("rec_cache_hits_total", "Попадания в кэш", ["kind"])
CACHE_MISSES = Counter("rec_cache_misses_total", "Промахи кэша", ["kind"])

_pool: redis.Redis | None = None


async def init_pool() -> None:
    """Инициализация пула соединений с Redis."""
    global _pool
    _pool = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    # ping проверяет, что Redis доступен на старте
    await _pool.ping()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _key(prefix: str, user_id: int, n: int) -> str:
    return f"{prefix}:{user_id}:n={n}"


async def get(prefix: str, user_id: int, n: int) -> list[dict] | None:
    """Возвращает закэшированный результат либо None при промахе."""
    if _pool is None:
        return None
    raw = await _pool.get(_key(prefix, user_id, n))
    if raw is None:
        CACHE_MISSES.labels(kind=prefix).inc()
        return None
    CACHE_HITS.labels(kind=prefix).inc()
    return json.loads(raw)


async def set(prefix: str, user_id: int, n: int, value: list[dict]) -> None:
    """Сохраняет результат в кэш с заданным TTL."""
    if _pool is None:
        return
    await _pool.set(_key(prefix, user_id, n), json.dumps(value),
                    ex=CACHE_TTL_SECONDS)
