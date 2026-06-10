"""
Заготовка параметров запросов из ratings.csv для k6.

Читает полный ratings.csv набора MovieLens и формирует компактный JSON-файл
с заранее отобранными парами (user_id, movie_id). Это избавляет от загрузки
файла CSV на 600 МБ в среду выполнения k6 на JavaScript.

Отбор сохраняет естественное распределение: пользователи с большим числом оценок
попадают в выборку чаще (тот же принцип, что и в нагрузочном скрипте k6, см. §3.1).

Запуск:
    python generate_params.py [--n 100000] [--seed 42]
    Результат: data/k6_params.json
"""

import csv
import json
import random
import sys
from pathlib import Path

RATINGS_PATH = Path(__file__).parent / "data" / "ratings.csv"
OUTPUT_PATH = Path(__file__).parent / "data" / "k6_params.json"

DEFAULT_N = 200_000  # достаточно для случайной выборки без 600 МБ в памяти
DEFAULT_SEED = 42


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--n", type=int, default=DEFAULT_N,
                        help=f"число выборок (по умолчанию {DEFAULT_N})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    print(f"Чтение {RATINGS_PATH}...")
    user_ids = []
    movie_ids = []
    with open(RATINGS_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # пропускаем строку заголовка
        for row in reader:
            user_ids.append(int(row[0]))
            movie_ids.append(int(row[1]))

    total = len(user_ids)
    print(f"Всего строк: {total:,}")

    rng = random.Random(args.seed)
    indices = [rng.randrange(total) for _ in range(args.n)]

    params = []
    for i in indices:
        params.append({"u": user_ids[i], "m": movie_ids[i]})

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(params, f)

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Записано выборок: {len(params):,} в {OUTPUT_PATH} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
