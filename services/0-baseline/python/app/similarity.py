"""
Загрузка модели сходства фильмов из БД в оперативную память.

Модель: dict[movie_id -> list[(similar_movie_id, similarity)]]
Загружается один раз при старте сервиса.
"""

import time
from collections import defaultdict

import psycopg2
from app.config import DATABASE_URL


# Глобальная модель: {movie_id: [(similar_movie_id, similarity), ...]}
_model: dict[int, list[tuple[int, float]]] = {}
_model_loaded = False
_load_time_seconds = 0.0


def load_model():
    """Загружает item_similarity из PostgreSQL в оперативную память."""
    global _model, _model_loaded, _load_time_seconds

    start = time.monotonic()
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT movie_id, similar_movie_id, similarity "
                "FROM item_similarity ORDER BY movie_id, similarity DESC"
            )
            model = defaultdict(list)
            count = 0
            for movie_id, similar_id, sim in cur:
                model[movie_id].append((similar_id, sim))
                count += 1
    finally:
        conn.close()

    _model = dict(model)
    _model_loaded = True
    _load_time_seconds = time.monotonic() - start
    print(
        f"Модель загружена: {len(_model)} фильмов, "
        f"{count} пар, {_load_time_seconds:.1f}с"
    )


def get_neighbors(movie_id: int) -> list[tuple[int, float]]:
    """Возвращает K ближайших соседей фильма."""
    return _model.get(movie_id, [])


def is_loaded() -> bool:
    return _model_loaded


def load_time() -> float:
    return _load_time_seconds
