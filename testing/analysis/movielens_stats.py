"""
Анализ распределения активности пользователей в MovieLens ratings.csv.

Используется в §3.1 ВКР для обоснования выбора параметров запросов
из случайных строк датасета: активные пользователи автоматически
попадают в поток чаще, потому что их строк в файле больше.

Запуск (через Docker с подмонтированным volume movielens-data):
    docker run --rm -v compose_movielens-data:/data python:3.12-slim \
        python /path/to/movielens_stats.py /data/ml-25m/ratings.csv

Либо локально, если ratings.csv распакован рядом:
    python movielens_stats.py ./ratings.csv
"""

import csv
import sys
from collections import Counter


def analyze(ratings_csv_path: str) -> None:
    user_counts: Counter[str] = Counter()
    total = 0

    with open(ratings_csv_path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            user_counts[row[0]] += 1
            total += 1

    counts_desc = sorted(user_counts.values(), reverse=True)
    counts_asc = sorted(user_counts.values())
    n = len(counts_desc)

    def pct(p: float) -> int:
        idx = max(0, min(n - 1, int(n * p / 100)))
        return counts_asc[idx]

    print(f"Пользователей: {n:,}")
    print(f"Оценок:        {total:,}")
    print(f"Среднее:       {total / n:.1f}")
    print(f"Медиана:       {counts_asc[n // 2]}")
    print(f"Минимум:       {min(counts_asc)}, максимум: {max(counts_asc):,}")
    print()
    print("Процентили:")
    for p in (25, 50, 75, 90, 95, 99):
        print(f"  p{p}: {pct(p)}")
    print()
    print("Доля оценок у наиболее активных пользователей:")
    for k in (10, 20, 30, 50):
        top_users = int(n * k / 100)
        top_ratings = sum(counts_desc[:top_users])
        share = top_ratings / total * 100
        print(f"  Топ {k:>2}%: {top_users:>6,} польз., "
              f"{top_ratings:>12,} оценок ({share:.1f}%)")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/data/ml-25m/ratings.csv"
    analyze(path)
