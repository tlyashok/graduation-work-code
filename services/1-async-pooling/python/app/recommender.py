"""
Алгоритм формирования рекомендаций (онлайн-этап).

Коллаборативная фильтрация (item-based):
1. Загрузить оценки пользователя из БД
2. Для каждого оценённого фильма - извлечь K соседей из модели (оперативная память)
3. Вычислить взвешенные баллы для кандидатов
4. Нормализовать, ограничить [1, 5], отсортировать, взять top-N

Fallback: рекомендации по популярности (если оценок < 5).

Алгоритм идентичен этапу 0 - единственное отличие итерации 1 в том,
что обращения к БД асинхронные (через пул asyncpg).
"""

from __future__ import annotations

from app import database, similarity
from app.config import REC_MIN_RATINGS


async def recommend(user_id: int, n: int = 10) -> list[dict]:
    """
    Формирует персональные рекомендации.
    Автоматически переключается на fallback при < 5 оценках.
    """
    user_ratings = await database.fetch_user_ratings(user_id)

    if len(user_ratings) < REC_MIN_RATINGS:
        return await recommend_popular(user_id, n, user_ratings)

    return await _item_based_cf(user_ratings, n)


async def recommend_popular(
    user_id: int, n: int = 10, user_ratings: list | None = None
) -> list[dict]:
    """Рекомендации по популярности (fallback)."""
    if user_ratings is None:
        user_ratings = await database.fetch_user_ratings(user_id)

    rated_movie_ids = {mid for mid, _ in user_ratings}
    popular = await database.fetch_popular_movies(rated_movie_ids, n)

    return [
        {
            "movie_id": movie_id,
            "title": title,
            "predicted_rating": round(avg_rating, 2),
        }
        for movie_id, title, avg_rating in popular
    ]


async def get_similar(movie_id: int, n: int = 6) -> list[dict]:
    """Возвращает top-N похожих фильмов из модели."""
    neighbors = similarity.get_neighbors(movie_id)
    if not neighbors:
        return []

    top_n = neighbors[:n]
    movie_ids = [mid for mid, _ in top_n]
    titles = await database.fetch_movie_titles(movie_ids)

    return [
        {
            "movie_id": mid,
            "title": titles.get(mid, ""),
            "similarity": round(sim, 4),
        }
        for mid, sim in top_n
    ]


async def _item_based_cf(user_ratings: list[tuple[int, float]], n: int) -> list[dict]:
    """Коллаборативная фильтрация (item-based), онлайн-этап."""
    rated_movie_ids = {mid for mid, _ in user_ratings}

    # Аккумуляторы для кандидатов
    candidate_scores: dict[int, float] = {}
    candidate_weights: dict[int, float] = {}

    for movie_id, rating in user_ratings:
        neighbors = similarity.get_neighbors(movie_id)
        for similar_id, sim in neighbors:
            if similar_id in rated_movie_ids:
                continue
            weighted_score = rating * sim
            candidate_scores[similar_id] = (
                candidate_scores.get(similar_id, 0.0) + weighted_score
            )
            candidate_weights[similar_id] = (
                candidate_weights.get(similar_id, 0.0) + sim
            )

    # Нормализация и ограничение [1, 5]
    results = []
    for movie_id, total_score in candidate_scores.items():
        weight_sum = candidate_weights[movie_id]
        if weight_sum == 0:
            continue
        predicted = total_score / weight_sum
        predicted = max(1.0, min(5.0, predicted))
        results.append((movie_id, predicted))

    # Сортировка по предсказанной оценке
    results.sort(key=lambda x: x[1], reverse=True)
    top_n = results[:n]

    # Загрузить названия фильмов
    movie_ids = [mid for mid, _ in top_n]
    titles = await database.fetch_movie_titles(movie_ids)

    return [
        {
            "movie_id": movie_id,
            "title": titles.get(movie_id, ""),
            "predicted_rating": round(predicted, 2),
        }
        for movie_id, predicted in top_n
    ]
