"""
Итерация 0: psycopg2 + ThreadedConnectionPool(5).
Синхронный драйвер с фиксированным пулом из 5 соединений.
"""

import psycopg2
from psycopg2 import pool as pg_pool

from app.config import DATABASE_URL

_POOL: pg_pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Создаёт пул соединений (вызывается из FastAPI lifespan на старте)."""
    global _POOL
    if _POOL is None:
        _POOL = pg_pool.ThreadedConnectionPool(minconn=5, maxconn=5, dsn=DATABASE_URL)


def close_pool() -> None:
    """Закрывает пул (вызывается из FastAPI lifespan на shutdown)."""
    global _POOL
    if _POOL is not None:
        _POOL.closeall()
        _POOL = None


def _get_conn():
    if _POOL is None:
        raise RuntimeError("Пул соединений не инициализирован")
    return _POOL.getconn()


def _put_conn(conn) -> None:
    if _POOL is not None:
        _POOL.putconn(conn)


def fetch_user_ratings(user_id: int) -> list[tuple[int, float]]:
    """Загружает оценки пользователя: [(movie_id, rating), ...]."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT movie_id, rating FROM ratings WHERE user_id = %s",
                (user_id,),
            )
            return cur.fetchall()
    finally:
        _put_conn(conn)


def fetch_popular_movies(exclude_movie_ids: set[int], n: int) -> list[tuple[int, str, float]]:
    """Возвращает популярные фильмы: [(movie_id, title, avg_rating), ...].

    Сортировка по комбинированному баллу avg_rating * ln(ratings_count),
    но в результате возвращается avg_rating - для согласованной с основным
    эндпоинтом шкалы [0, 5] в поле predicted_rating ответа.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT movie_id, title, avg_rating
                FROM movies
                WHERE ratings_count > 0
                ORDER BY avg_rating * ln(ratings_count + 1) DESC
                LIMIT %s
            """, (n + len(exclude_movie_ids),))
            results = []
            for movie_id, title, avg_rating in cur.fetchall():
                if movie_id not in exclude_movie_ids and len(results) < n:
                    results.append((movie_id, title, avg_rating))
            return results
    finally:
        _put_conn(conn)


def fetch_movie_title(movie_id: int) -> str | None:
    """Возвращает название фильма."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM movies WHERE movie_id = %s", (movie_id,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        _put_conn(conn)


def fetch_movie_titles(movie_ids: list[int]) -> dict[int, str]:
    """Возвращает названия фильмов по списку ID."""
    if not movie_ids:
        return {}
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT movie_id, title FROM movies WHERE movie_id = ANY(%s)",
                (movie_ids,),
            )
            return dict(cur.fetchall())
    finally:
        _put_conn(conn)
