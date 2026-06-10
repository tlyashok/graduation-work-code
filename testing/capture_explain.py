"""
Снимает чистый по-итерационный профиль СУБД и планы выполнения горячих запросов.

Чтобы профиль БД относился именно к нагрузке данной итерации, pg_stat_statements
СБРАСЫВАЕТСЯ перед нагрузкой, а снимок снимается ПОСЛЕ неё и ДО EXPLAIN (иначе
сами EXPLAIN-запросы попадают в статистику и засоряют её). Порядок использования:

    python capture_explain.py reset                 # перед нагрузочным прогоном итерации
    # ... прогон под нагрузкой (профилирование / breakpoint) ...
    python capture_explain.py capture iter0_go --out results/explain --user-id 100

Команда capture сохраняет:
    <name>_pgstat.txt   - распределение времени СУБД по запросам (чистое, за нагрузку);
    <name>.txt          - EXPLAIN ANALYZE запроса пользователя (/recommendations);
    <name>_popular.txt  - EXPLAIN ANALYZE запроса популярного (/popular).
"""
import argparse
import subprocess
from pathlib import Path

DB_CONTAINER = "compose-db-1"
DEFAULT_OUT = Path(__file__).resolve().parent / "results" / "explain"


def psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DB_CONTAINER,
         "psql", "-U", "filmrec", "-d", "filmrec", "-X", "-c", sql],
        capture_output=True, text=True,
    )
    return r.stdout + r.stderr


def ensure_ext():
    psql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")


def cmd_reset():
    ensure_ext()
    print(psql("SELECT pg_stat_statements_reset();").strip())


def cmd_capture(name: str, out_dir: Path, user_id: int, explain: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_ext()

    # 1) pg_stat СНАЧАЛА - пока EXPLAIN-запросы ещё не засорили статистику.
    pgstat_sql = (
        "SELECT round(total_exec_time::numeric, 1) AS total_ms, calls, "
        "round(mean_exec_time::numeric, 3) AS mean_ms, "
        "round((100 * total_exec_time / NULLIF(sum(total_exec_time) OVER (), 0))::numeric, 1) AS pct, "
        "left(regexp_replace(query, '\\s+', ' ', 'g'), 90) AS query "
        "FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;"
    )
    pgstat = psql(pgstat_sql)
    (out_dir / f"{name}_pgstat.txt").write_text(pgstat, encoding="utf-8")
    print(f"pg_stat сохранён: {out_dir}/{name}_pgstat.txt")
    print(pgstat[:700])

    # 2) EXPLAIN планов (детерминированы планом, не зависят от числа повторов).
    if explain:
        user_sql = (
            "EXPLAIN (ANALYZE, BUFFERS) "
            f"SELECT movie_id, rating FROM ratings WHERE user_id = {user_id};"
        )
        popular_sql = (
            "EXPLAIN (ANALYZE, BUFFERS) "
            "SELECT movie_id, title, avg_rating FROM movies WHERE ratings_count > 0 "
            "ORDER BY avg_rating * ln(ratings_count + 1) DESC LIMIT 81;"
        )
        (out_dir / f"{name}.txt").write_text(psql(user_sql), encoding="utf-8")
        (out_dir / f"{name}_popular.txt").write_text(psql(popular_sql), encoding="utf-8")
        print(f"EXPLAIN сохранён: {out_dir}/{name}.txt, {name}_popular.txt")


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("reset", help="сбросить pg_stat_statements перед нагрузкой")
    c = sub.add_parser("capture", help="снять pg_stat (+EXPLAIN) после нагрузки")
    c.add_argument("name", help="имя для файлов (например iter0_go)")
    c.add_argument("--out", type=Path, default=DEFAULT_OUT, help="каталог вывода")
    c.add_argument("--user-id", type=int, default=100)
    c.add_argument("--no-explain", action="store_true", help="не снимать EXPLAIN")

    # Совместимость со старым вызовом `capture_explain.py iter0`:
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] not in ("reset", "capture", "-h", "--help"):
        sys.argv.insert(1, "capture")

    args = p.parse_args()
    if args.action == "reset":
        cmd_reset()
    else:
        cmd_capture(args.name, args.out, args.user_id, not args.no_explain)


if __name__ == "__main__":
    main()
