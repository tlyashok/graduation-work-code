"""Prometheus метрики для рекомендательного сервиса."""

from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    "rec_requests_total",
    "Общее число запросов",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION = Histogram(
    "rec_request_duration_seconds",
    "Длительность обработки запроса, секунды",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

REQUEST_ERRORS = Counter(
    "rec_errors_total",
    "Общее число ошибок",
    ["method", "endpoint"],
)

MODEL_LOAD_TIME = Gauge(
    "rec_model_load_time_seconds",
    "Время загрузки модели сходства, секунды",
)

# Уникальные пользователи, попавшие в запросы за прогон. Считается так же, как
# кэш-хиты: счётчик в приложении, отдаётся через /metrics и снимается Prometheus.
# Показывает концентрацию нагрузки и объясняет эффективность кэша (§3.4).
UNIQUE_USERS = Gauge("rec_unique_users", "Уникальных пользователей в запросах за прогон")
_seen_users: set[int] = set()


def observe_user(user_id: int) -> None:
    """Учитывает пользователя в метрике уникальных (идемпотентно)."""
    if user_id not in _seen_users:
        _seen_users.add(user_id)
        UNIQUE_USERS.set(len(_seen_users))
