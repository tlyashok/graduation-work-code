import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://filmrec:filmrec@localhost:5432/filmrec")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Алгоритм
REC_N_DEFAULT = int(os.getenv("REC_N_DEFAULT", "10"))      # количество рекомендаций по умолчанию
REC_MIN_RATINGS = int(os.getenv("REC_MIN_RATINGS", "5"))    # минимум оценок для персональных рекомендаций (иначе fallback)
