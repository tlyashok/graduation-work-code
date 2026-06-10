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
