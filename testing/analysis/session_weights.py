"""
Подсчёт пропорций вызовов эндпоинтов рекомендательного сервиса по журналу nginx access.log.

Используется в §3.1 ВКР: автор вручную проходит типовые сессии (в работе - два прохода) в
веб-системе под ролью «пользователь», nginx логирует все вызовы, скрипт
считает доли вызовов трёх эндпоинтов и выдаёт веса для нагрузочного скрипта k6.

Эндпоинты:
    GET /recommendations/{user_id}              - персональные рекомендации
    GET /recommendations/{user_id}/popular      - рекомендации по популярности
    GET /similar/{movie_id}                     - похожие фильмы

Запуск:
    python session_weights.py path/to/access.log

С сохранением сводки в JSON:
    python session_weights.py path/to/access.log --json weights.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

PERSONAL_RE = re.compile(r'"GET /recommendations/\d+(?:\?|\s+HTTP)')
POPULAR_RE = re.compile(r'"GET /recommendations/\d+/popular')
SIMILAR_RE = re.compile(r'"GET /similar/\d+')


def count_endpoints(log_path: Path) -> dict[str, int]:
    counts = {"personal": 0, "popular": 0, "similar": 0}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if POPULAR_RE.search(line):
                counts["popular"] += 1
            elif PERSONAL_RE.search(line):
                counts["personal"] += 1
            elif SIMILAR_RE.search(line):
                counts["similar"] += 1
    return counts


def task_weights(counts: dict[str, int]) -> dict[str, int]:
    """Округляет доли до целых процентов с поправкой суммы до 100."""
    total = sum(counts.values())
    if total == 0:
        return {k: 0 for k in counts}
    raw = {k: v / total * 100 for k, v in counts.items()}
    rounded = {k: round(v) for k, v in raw.items()}
    diff = 100 - sum(rounded.values())
    if diff:
        # Поправляем разность на ключе с наибольшим вкладом
        leader = max(rounded, key=rounded.get)
        rounded[leader] += diff
    return rounded


def report(log_path: Path, json_path: Path | None = None) -> None:
    counts = count_endpoints(log_path)
    total = sum(counts.values())
    weights = task_weights(counts)

    print(f"access.log: {log_path}")
    print(f"вызовов к рекомендательному сервису: {total}")
    print()

    if total == 0:
        print("В логе нет вызовов к рекомендательному сервису.")
        return

    print(f"{'эндпоинт':<45} {'вызовов':>10} {'доля':>8} {'вес':>7}")
    print("-" * 72)
    for key, label in [
        ("personal", "/recommendations/{user_id}"),
        ("popular", "/recommendations/{user_id}/popular"),
        ("similar", "/similar/{movie_id}"),
    ]:
        share = counts[key] / total * 100
        print(f"{label:<45} {counts[key]:>10} {share:>7.1f}% {weights[key]:>7}")
    print("-" * 72)
    print(f"{'итого':<45} {total:>10} {'100.0%':>8} {sum(weights.values()):>7}")

    if json_path:
        result = {
            "source": str(log_path),
            "total_calls": total,
            "counts": counts,
            "shares_percent": {k: round(v / total * 100, 2) for k, v in counts.items()},
            "task_weights": weights,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nСводка сохранена: {json_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("log_path", type=Path, help="путь к access.log")
    parser.add_argument("--json", type=Path, default=None, help="сохранить сводку в JSON")
    args = parser.parse_args()

    if not args.log_path.is_file():
        print(f"Файл не найден: {args.log_path}", file=sys.stderr)
        sys.exit(1)

    report(args.log_path, args.json)


if __name__ == "__main__":
    main()
