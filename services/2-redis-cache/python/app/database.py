"""
Итерация 1: asyncpg, асинхронный драйвер с пулом соединений.

Пул создаётся один раз при старте сервиса (lifespan FastAPI),
переиспользуется всеми обработчиками. Размер пула фиксирован
(min=max=10), см. §2.5.
"""

from __future__ import annotations

import asyncpg

from app.config import DATABASE_URL, DB_POOL_MIN_SIZE, DB_POOL_MAX_SIZE


_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Создаёт пул соединений и обеспечивает наличие индекса по ratings.user_id.

    Индекс - часть итерации 1 по объединённому плану §2.5 (см. §3.3):
    без него пул из 10 соединений упирается в последовательный скан
    таблицы ratings (25 млн строк), и устранение накладных расходов
    на установление соединения не даёт прироста пропускной способности.
    """
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=DB_POOL_MIN_SIZE,
        max_size=DB_POOL_MAX_SIZE,
    )
    async with _pool.acquire() as conn:
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ratings_user_id ON ratings(user_id)"
        )
        # Индекс под /popular: ранжирование по популярности было seq scan'ом всех
        # 62К фильмов на каждый запрос (узкое место БД при высоком RPS Go). Частичный
        # индекс по выражению превращает ORDER BY ... LIMIT в index scan.
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_popularity "
            "ON movies ((avg_rating * ln(ratings_count + 1)) DESC) "
            "WHERE ratings_count > 0"
        )


async def close_pool() -> None:
    """Закрывает пул при остановке сервиса."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Пул соединений с базой данных не инициализирован")
    return _pool


async def fetch_user_ratings(user_id: int) -> list[tuple[int, float]]:
    """Загружает оценки пользователя: [(movie_id, rating), ...]."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT movie_id, rating FROM ratings WHERE user_id = $1",
        user_id,
    )
    return [(r["movie_id"], r["rating"]) for r in rows]


async def fetch_popular_movies(
    exclude_movie_ids: set[int], n: int
) -> list[tuple[int, str, float]]:
    """Возвращает популярные фильмы: [(movie_id, title, avg_rating), ...].

    Сортировка по комбинированному баллу avg_rating * ln(ratings_count),
    но в результате возвращается avg_rating - для согласованной с основным
    эндпоинтом шкалы [0, 5] в поле predicted_rating ответа.
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT movie_id, title, avg_rating
        FROM movies
        WHERE ratings_count > 0
        ORDER BY avg_rating * ln(ratings_count + 1) DESC
        LIMIT $1
        """,
        n + len(exclude_movie_ids),
    )
    results: list[tuple[int, str, float]] = []
    for row in rows:
        if row["movie_id"] not in exclude_movie_ids and len(results) < n:
            results.append((row["movie_id"], row["title"], row["avg_rating"]))
    return results


async def fetch_movie_title(movie_id: int) -> str | None:
    """Возвращает название фильма."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT title FROM movies WHERE movie_id = $1",
        movie_id,
    )
    return row["title"] if row else None


async def fetch_movie_titles(movie_ids: list[int]) -> dict[int, str]:
    """Возвращает названия фильмов по списку ID."""
    if not movie_ids:
        return {}
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT movie_id, title FROM movies WHERE movie_id = ANY($1::int[])",
        movie_ids,
    )
    return {r["movie_id"]: r["title"] for r in rows}
