"""
Офлайн-этап: вычисление модели сходства фильмов (item_similarity).

Алгоритм: скорректированная косинусная мера сходства между парами фильмов.
Для каждого фильма сохраняются K ближайших соседей.
Использует разреженную матрицу scipy для быстрого вычисления.

Использование:
    python compute_similarity.py
"""

import io
import os
import sys
import time

import numpy as np
import psycopg2
from scipy.sparse import csr_matrix
from sklearn.metrics.pairwise import cosine_similarity

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://filmrec:filmrec@localhost:5432/filmrec")
K = int(os.getenv("SIMILARITY_K", "30"))
MIN_COMMON = int(os.getenv("SIMILARITY_MIN_COMMON", "5"))
MIN_RATINGS = int(os.getenv("SIMILARITY_MIN_RATINGS", "10"))


def load_ratings(cur):
    """Загружает оценки и строит разреженную матрицу пользователь-фильм."""
    # Фильмы с малым числом оценок исключаются: косинусная мера
    # по < MIN_RATINGS точкам статистически ненадёжна
    print(f"Загрузка оценок (MIN_RATINGS={MIN_RATINGS})...")
    cur.execute("""
        SELECT r.user_id, r.movie_id, r.rating
        FROM ratings r
        JOIN (
            SELECT movie_id FROM ratings
            GROUP BY movie_id HAVING COUNT(*) >= %s
        ) popular ON r.movie_id = popular.movie_id
    """, (MIN_RATINGS,))
    rows = cur.fetchall()
    print(f"  Загружено оценок: {len(rows)}")

    user_ids_raw = [r[0] for r in rows]
    movie_ids_raw = [r[1] for r in rows]
    ratings = [r[2] for r in rows]

    # Маппинг в непрерывные индексы
    unique_users = sorted(set(user_ids_raw))
    unique_movies = sorted(set(movie_ids_raw))
    user_map = {uid: idx for idx, uid in enumerate(unique_users)}
    movie_map = {mid: idx for idx, mid in enumerate(unique_movies)}

    row_idx = [user_map[u] for u in user_ids_raw]
    col_idx = [movie_map[m] for m in movie_ids_raw]

    n_users = len(unique_users)
    n_movies = len(unique_movies)
    print(f"  Пользователей: {n_users}, фильмов: {n_movies}")

    # Разреженная матрица пользователь-фильм
    matrix = csr_matrix(
        (ratings, (row_idx, col_idx)),
        shape=(n_users, n_movies),
        dtype=np.float32,
    )

    return matrix, unique_movies, movie_map


def compute_similarities(matrix, unique_movies, k, min_common):
    """Вычисляет K ближайших соседей для каждого фильма."""
    n_movies = len(unique_movies)
    print(f"Вычисление сходства для {n_movies} фильмов (K={k}, min_common={min_common})...")

    start = time.time()

    # Скорректированная мера: вычитаем среднюю оценку каждого пользователя
    # (среднее только по реально оценённым фильмам, не по всем столбцам)
    sums = np.asarray(matrix.sum(axis=1)).ravel()
    counts = np.diff(matrix.indptr)
    user_means = np.divide(
        sums, counts,
        out=np.zeros_like(sums, dtype=np.float64),
        where=counts != 0,
    )
    # Для разреженной матрицы - вычитаем только ненулевые элементы
    matrix_centered = matrix.copy().astype(np.float64)
    rows, cols = matrix_centered.nonzero()
    matrix_centered[rows, cols] -= user_means[rows]

    binary = (matrix > 0).astype(np.float32)
    item_matrix = matrix_centered.T.tocsr()  # фильм-пользователь
    binary_item = binary.T.tocsr()            # фильм-пользователь

    # Считаем батчами по фильмам, чтобы не строить полную матрицу 62K на 62K
    BATCH = 1000
    print(f"  Вычисление косинусной меры батчами по {BATCH} фильмов...")
    similarities = {}

    for start_i in range(0, n_movies, BATCH):
        end_i = min(start_i + BATCH, n_movies)
        batch = item_matrix[start_i:end_i]
        batch_binary = binary_item[start_i:end_i]

        # косинусная мера сходства: батч на все фильмы
        sim_block = cosine_similarity(batch, item_matrix)
        # число общих пользователей: батч на все фильмы
        common_block = (batch_binary @ binary_item.T).toarray()

        # Обнулить пары с недостаточным числом общих пользователей, отрицательные, диагональ
        sim_block[common_block < min_common] = 0
        sim_block[sim_block < 0] = 0
        for local_i in range(end_i - start_i):
            sim_block[local_i, start_i + local_i] = 0  # диагональ

        # Top-K для каждого фильма в батче
        for local_i in range(end_i - start_i):
            global_i = start_i + local_i
            movie_id = unique_movies[global_i]
            row = sim_block[local_i]

            nonzero_mask = row > 0
            if not np.any(nonzero_mask):
                continue

            nonzero_idx = np.where(nonzero_mask)[0]
            nonzero_vals = row[nonzero_idx]
            if len(nonzero_idx) > k:
                top_local = np.argpartition(nonzero_vals, -k)[-k:]
            else:
                top_local = np.arange(len(nonzero_idx))
            top_local = top_local[np.argsort(nonzero_vals[top_local])[::-1]]

            neighbors = [(unique_movies[nonzero_idx[j]], float(nonzero_vals[j])) for j in top_local]
            similarities[movie_id] = neighbors

        progress = min(end_i, n_movies)
        print(f"  Прогресс: {progress}/{n_movies} ({100*progress/n_movies:.0f}%)")

    elapsed = time.time() - start
    total_pairs = sum(len(v) for v in similarities.values())
    print(f"  Завершено за {elapsed:.1f}с. Фильмов с соседями: {len(similarities)}, пар: {total_pairs}")
    return similarities


def save_similarities(cur, similarities):
    """Сохраняет модель в таблицу item_similarity."""
    print("Сохранение в item_similarity...")
    cur.execute("TRUNCATE item_similarity")

    buf = io.StringIO()
    count = 0
    for movie_id, neighbors in similarities.items():
        for similar_id, score in neighbors:
            buf.write(f"{movie_id}\t{similar_id}\t{score:.6f}\n")
            count += 1

    buf.seek(0)
    cur.copy_from(
        buf, "item_similarity", columns=("movie_id", "similar_movie_id", "similarity")
    )
    print(f"  Сохранено пар: {count}")


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        matrix, unique_movies, movie_map = load_ratings(cur)
        similarities = compute_similarities(matrix, unique_movies, K, MIN_COMMON)
        save_similarities(cur, similarities)
        conn.commit()
        print("\nМодель сходства вычислена и сохранена!")
    except Exception as e:
        conn.rollback()
        print(f"\nОшибка: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
