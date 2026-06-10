"""
Рекомендательный сервис - итерация 1 (asyncpg + async-обработчики FastAPI).

Отличия от этапа 0:
- драйвер БД: asyncpg вместо psycopg2;
- пул соединений (min=max=10), создаётся в lifespan;
- все обработчики async def, работают через цикл событий FastAPI.

Алгоритм рекомендаций - без изменений (см. recommender.py).
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app import similarity, database, recommender
from app.metrics import (
    REQUEST_COUNT,
    REQUEST_DURATION,
    REQUEST_ERRORS,
    MODEL_LOAD_TIME,
)
from app.schemas import RecommendationItem, SimilarItem, HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старте: пул соединений + загрузка модели сходства в оперативную память
    await database.init_pool()
    await similarity.load_model()
    MODEL_LOAD_TIME.set(similarity.load_time())
    try:
        yield
    finally:
        await database.close_pool()


app = FastAPI(title="FilmRec Recommendation Service", lifespan=lifespan)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration = time.monotonic() - start

    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path)
    method = request.method
    status = f"{response.status_code // 100}xx"

    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
    REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)

    if response.status_code >= 500:
        REQUEST_ERRORS.labels(method=method, endpoint=endpoint).inc()

    return response


@app.get(
    "/recommendations/{user_id}",
    response_model=list[RecommendationItem],
)
async def get_recommendations(user_id: int, n: int = Query(default=None, ge=1, le=100)):
    from app.config import REC_N_DEFAULT
    if n is None:
        n = REC_N_DEFAULT

    results = await recommender.recommend(user_id, n)
    return results


@app.get(
    "/recommendations/{user_id}/popular",
    response_model=list[RecommendationItem],
)
async def get_popular(user_id: int, n: int = Query(default=None, ge=1, le=100)):
    from app.config import REC_N_DEFAULT
    if n is None:
        n = REC_N_DEFAULT

    results = await recommender.recommend_popular(user_id, n)
    return results


@app.get("/similar/{movie_id}", response_model=list[SimilarItem])
async def similar(movie_id: int, n: int = Query(default=6, ge=1, le=100)):
    results = await recommender.get_similar(movie_id, n)
    if not results:
        raise HTTPException(status_code=404, detail="Фильм не найден в модели сходства")
    return results


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", model_loaded=similarity.is_loaded())


@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
