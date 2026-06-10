"""
Загрузка датасета MovieLens 25M в PostgreSQL.

Использование:
    python seed_movielens.py

Датасет: https://files.grouplens.org/datasets/movielens/ml-25m.zip
Содержит: 25M оценок, 162K пользователей, 62K фильмов.
"""

import csv
import io
import json
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import psycopg2

DATASET = os.getenv("MOVIELENS_DATASET", "ml-25m")  # ml-25m | ml-latest-small
MOVIELENS_URL = f"https://files.grouplens.org/datasets/movielens/{DATASET}.zip"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://filmrec:filmrec@localhost:5432/filmrec")
DATA_DIR = Path(os.getenv("MOVIELENS_DATA_DIR", str(Path(tempfile.gettempdir()) / "movielens")))


def download_and_extract(dest_dir: Path) -> Path:
    """Скачивает и распаковывает датасет MovieLens."""
    zip_path = dest_dir / f"{DATASET}.zip"
    extracted = dest_dir / DATASET

    if extracted.exists():
        print(f"Датасет уже распакован: {extracted}")
        return extracted

    if not zip_path.exists():
        print(f"Скачивание {MOVIELENS_URL} ...")
        urllib.request.urlretrieve(MOVIELENS_URL, zip_path)
        print(f"Скачано: {zip_path} ({zip_path.stat().st_size / 1e6:.0f} МБ)")

    print("Распаковка...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest_dir)
    print(f"Распаковано: {extracted}")
    return extracted


def load_movies(cur, data_dir: Path):
    """Загружает фильмы из movies.csv."""
    path = data_dir / "movies.csv"
    print(f"Загрузка фильмов из {path.name}...")

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        batch = []
        for row in reader:
            movie_id = int(row["movieId"])
            title = row["title"].strip()
            # Извлечь год из заголовка, например "Toy Story (1995)"
            year = None
            if title.endswith(")") and "(" in title:
                try:
                    year = int(title[title.rfind("(") + 1 : title.rfind(")")])
                    title = title[: title.rfind("(")].strip()
                except ValueError:
                    pass
            genres_str = row["genres"]
            batch.append((movie_id, title, year, genres_str))

        # Вставка фильмов
        buf = io.StringIO()
        for movie_id, title, year, _ in batch:
            year_str = str(year) if year else "\\N"
            buf.write(f"{movie_id}\t{title}\t{year_str}\n")
        buf.seek(0)
        cur.copy_from(buf, "movies", columns=("movie_id", "title", "year"))
        print(f"  Загружено фильмов: {len(batch)}")

        # Извлечение и вставка жанров
        all_genres = set()
        for _, _, _, genres_str in batch:
            if genres_str != "(no genres listed)":
                all_genres.update(genres_str.split("|"))

        for genre in sorted(all_genres):
            cur.execute(
                "INSERT INTO genres (name) VALUES (%s) ON CONFLICT DO NOTHING",
                (genre,),
            )
        cur.execute("SELECT genre_id, name FROM genres")
        genre_map = {name: gid for gid, name in cur.fetchall()}

        # movie_genres
        buf = io.StringIO()
        count = 0
        for movie_id, _, _, genres_str in batch:
            if genres_str != "(no genres listed)":
                for g in genres_str.split("|"):
                    if g in genre_map:
                        buf.write(f"{movie_id}\t{genre_map[g]}\n")
                        count += 1
        buf.seek(0)
        cur.copy_from(buf, "movie_genres", columns=("movie_id", "genre_id"))
        print(f"  Загружено связей фильм-жанр: {count}")


def load_ratings(cur, data_dir: Path):
    """Загружает оценки из ratings.csv через COPY."""
    path = data_dir / "ratings.csv"
    print(f"Загрузка оценок из {path.name} (это займёт несколько минут)...")

    # Сначала создаём пользователей (уникальные user_id из ratings)
    user_ids = set()
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_ids.add(int(row["userId"]))

    buf = io.StringIO()
    for uid in sorted(user_ids):
        buf.write(f"{uid}\tuser_{uid}\tuser_{uid}@movielens.org\t\\N\t\\N\t\\N\tuser\tactive\t0\t\\N\n")
    buf.seek(0)
    cur.copy_from(
        buf,
        "users",
        columns=(
            "user_id", "username", "email", "password_hash",
            "oauth_provider", "oauth_id", "role", "status",
            "failed_login_attempts", "locked_until",
        ),
    )
    print(f"  Создано пользователей: {len(user_ids)}")

    # Загрузка оценок
    buf = io.StringIO()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row["userId"]
            mid = row["movieId"]
            rating = row["rating"]
            ts = row["timestamp"]
            buf.write(f"{uid}\t{mid}\t{rating}\t{ts}\n")
            count += 1
    buf.seek(0)

    # Временная таблица для COPY с timestamp как integer
    cur.execute("""
        CREATE TEMP TABLE ratings_tmp (
            user_id BIGINT, movie_id BIGINT, rating FLOAT, ts BIGINT
        )
    """)
    cur.copy_from(buf, "ratings_tmp")
    cur.execute("""
        INSERT INTO ratings (user_id, movie_id, rating, created_at)
        SELECT user_id, movie_id, rating, to_timestamp(ts)
        FROM ratings_tmp
        ON CONFLICT (user_id, movie_id) DO NOTHING
    """)
    cur.execute("DROP TABLE ratings_tmp")
    print(f"  Загружено оценок: {count}")

    # Обновить avg_rating и ratings_count
    print("  Обновление avg_rating и ratings_count...")
    cur.execute("""
        UPDATE movies m SET
            avg_rating = sub.avg_r,
            ratings_count = sub.cnt
        FROM (
            SELECT movie_id, AVG(rating) as avg_r, COUNT(*) as cnt
            FROM ratings GROUP BY movie_id
        ) sub
        WHERE m.movie_id = sub.movie_id
    """)


def load_links(cur, data_dir: Path):
    """Загружает tmdb_id из links.csv напрямую в movies."""
    path = data_dir / "links.csv"
    if not path.exists():
        print("  links.csv не найден, пропуск")
        return

    print(f"Загрузка tmdb_id из {path.name}...")
    cur.execute("CREATE TEMP TABLE links_tmp (movie_id BIGINT, tmdb_id INTEGER)")
    buf = io.StringIO()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tmdb = row.get("tmdbId", "").strip()
            if not tmdb:
                continue
            buf.write(f"{row['movieId']}\t{tmdb}\n")
            count += 1
    buf.seek(0)
    cur.copy_from(buf, "links_tmp", columns=("movie_id", "tmdb_id"))
    cur.execute("""
        UPDATE movies m SET tmdb_id = lt.tmdb_id
        FROM links_tmp lt
        WHERE m.movie_id = lt.movie_id
    """)
    cur.execute("DROP TABLE links_tmp")
    print(f"  Обновлён tmdb_id у {count} фильмов")


def load_posters(cur):
    """Загружает poster_path с TMDB API для фильмов с tmdb_id."""
    tmdb_key = os.getenv("TMDB_API_KEY", "")
    if not tmdb_key:
        print("  TMDB_API_KEY не задан, постеры пропущены")
        return

    cur.execute("SELECT movie_id, tmdb_id FROM movies WHERE tmdb_id IS NOT NULL AND poster_path IS NULL")
    rows = cur.fetchall()
    print(f"Загрузка постеров с TMDB API ({len(rows)} фильмов)...")

    # Настроить прокси если задан
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        print(f"  Прокси: {proxy}")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_tmdb(tmdb_id):
        try:
            url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={tmdb_key}&language=ru-RU"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with opener.open(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("poster_path"), data.get("overview", "")
        except Exception:
            return None, None

    updated = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(fetch_tmdb, tmdb_id): (movie_id, tmdb_id) for movie_id, tmdb_id in rows}
        for i, future in enumerate(as_completed(futures)):
            movie_id, tmdb_id = futures[future]
            poster, overview = future.result()
            if poster or overview:
                cur.execute(
                    "UPDATE movies SET poster_path = COALESCE(%s, poster_path), description = COALESCE(%s, description) WHERE movie_id = %s",
                    (poster, overview or None, movie_id),
                )
                updated += 1
            else:
                errors += 1

            if (i + 1) % 500 == 0:
                print(f"  Прогресс: {i + 1}/{len(rows)}, постеров: {updated}, ошибок: {errors}")

    print(f"  Загружено постеров: {updated}, ошибок: {errors}")


def reset_sequences(cur):
    """Сбрасывает автоинкремент после bulk insert."""
    for table, col in [
        ("users", "user_id"),
        ("movies", "movie_id"),
        ("genres", "genre_id"),
        ("ratings", "rating_id"),
    ]:
        cur.execute(f"""
            SELECT setval(pg_get_serial_sequence('{table}', '{col}'),
                          COALESCE(MAX({col}), 1)) FROM {table}
        """)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ml_dir = download_and_extract(DATA_DIR)

    print(f"Подключение к БД: {DATABASE_URL}")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        load_movies(cur, ml_dir)
        load_ratings(cur, ml_dir)
        load_links(cur, ml_dir)
        reset_sequences(cur)
        conn.commit()
        # Постеры - опционально (LOAD_POSTERS=true в .env)
        if os.getenv("LOAD_POSTERS", "false").lower() == "true":
            conn.autocommit = True
            load_posters(cur)
        else:
            print("\nПостеры пропущены (LOAD_POSTERS=false)")
        print("\nЗагрузка завершена успешно!")
    except Exception as e:
        conn.rollback()
        print(f"\nОшибка: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
