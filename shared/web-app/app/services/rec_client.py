"""HTTP-клиент рекомендательного сервиса."""

import httpx
from app.config import RECOMMENDATION_SERVICE_URL


async def get_recommendations(user_id: int, n: int = 10) -> list[dict]:
    """Получает персональные рекомендации от рекомендательного сервиса."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{RECOMMENDATION_SERVICE_URL}/recommendations/{user_id}",
                params={"n": n},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        pass
    return []


async def get_similar(movie_id: int, n: int = 6) -> list[dict]:
    """Получает похожие фильмы от рекомендательного сервиса."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{RECOMMENDATION_SERVICE_URL}/similar/{movie_id}",
                params={"n": n},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        pass
    return []


async def get_popular(user_id: int, n: int = 10) -> list[dict]:
    """Получает популярные фильмы (fallback)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{RECOMMENDATION_SERVICE_URL}/recommendations/{user_id}/popular",
                params={"n": n},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        pass
    return []
