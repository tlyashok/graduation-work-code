import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://filmrec:filmrec@localhost:5432/filmrec")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Алгоритм
REC_N_DEFAULT = int(os.getenv("REC_N_DEFAULT", "10"))      # количество рекомендаций по умолчанию
REC_MIN_RATINGS = int(os.getenv("REC_MIN_RATINGS", "5"))    # минимум оценок для персональных рекомендаций (иначе fallback)

# Пул соединений к PostgreSQL (итерация 1, §2.5).
# Размер пула одинаков для Python и Go - для чистоты сравнения.
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "10"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

# Кэш Redis (итерация 2, §2.5).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
