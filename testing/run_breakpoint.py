"""
Поиск ёмкости: максимум запросов в секунду на пороге SLO при линейном росте нагрузки.

Запускает k6 в режиме ramping-arrival-rate (рост от 0 до MAX_RPS за время DURATION),
затем берёт у Prometheus временные ряды и находит момент, когда
95-й процентиль превышает порог 500 мс. Число запросов в секунду в этой точке и есть ёмкость.

Запуск:
    python run_breakpoint.py python --iter 1
    python run_breakpoint.py go --iter 2 --suffix ttl600 --max-rps 1200
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
K6_SCRIPT = REPO_ROOT / "testing" / "k6" / "breakpoint.js"


def _k6_bin() -> str:
    """Ищет бинарь k6 кроссплатформенно: переменная K6_BIN, затем PATH,
    затем привычные пути (Linux-сервер и Windows-машина разработки)."""
    env = os.environ.get("K6_BIN")
    if env:
        return env
    found = shutil.which("k6")
    if found:
        return found
    for candidate in (Path.home() / "bin" / "k6", Path.home() / "bin" / "k6.exe"):
        if candidate.exists():
            return str(candidate)
    return "k6"  # положимся на PATH


K6_BIN = _k6_bin()
RESULTS_ROOT = REPO_ROOT / "testing" / "results"

ITER_DIRS = {0: "0-baseline", 1: "1-async-pooling", 2: "2-redis-cache"}

REC_SERVICE_HOST = "http://127.0.0.1:8000"
PROMETHEUS_HOST = "http://127.0.0.1:9090"

SLO_P95 = 500   # мс
SLO_P99 = 1000  # мс


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def wait_health(timeout_sec: int = 180) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get(f"{REC_SERVICE_HOST}/health", timeout=3)
            if r.status_code == 200 and r.json().get("model_loaded"):
                log("проверка /health пройдена")
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    sys.exit("превышено время ожидания готовности сервиса")


def run_k6_ramp(max_rps: int, duration: str, summary_path: Path) -> tuple[float, float]:
    """Запускает прогон k6. Возвращает (start_time, end_time) как метки времени Unix.
    summary_path - куда k6 выгрузит итоговую сводку (нужна для доли ошибок)."""
    cmd = [
        str(K6_BIN), "run",
        # клиентские метрики k6 пишутся в Prometheus (p95/p99/ошибки со стороны
        # нагрузчика - видят и таймауты, в отличие от серверной гистограммы)
        "-o", "experimental-prometheus-rw",
        "--env", f"MAX_RPS={max_rps}",
        "--env", f"DURATION={duration}",
        "--env", f"BASE_URL={REC_SERVICE_HOST}",
        "--summary-export", str(summary_path),
        "--quiet",
        str(K6_SCRIPT),
    ]
    env = dict(os.environ)
    env["K6_PROMETHEUS_RW_SERVER_URL"] = f"{PROMETHEUS_HOST}/api/v1/write"
    env["K6_PROMETHEUS_RW_TREND_STATS"] = "p(95),p(99),avg,max"
    env["K6_PROMETHEUS_RW_PUSH_INTERVAL"] = "5s"
    log(f"k6: рост 0 -> {max_rps} запросов/с за {duration}")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    end = time.time()
    if result.returncode != 0:
        log(f"[!] k6 завершился с кодом {result.returncode}")
        for line in (result.stderr or "").strip().splitlines()[-5:]:
            log(f"    {line}")
    log(f"k6 завершён за {end - start:.0f} с")
    return start, end


def parse_k6_summary(summary_path: Path) -> dict:
    """Достаёт из сводки k6 общее число запросов и долю ошибок.
    Ошибкой считается ответ, не прошедший проверку (не 200 и не 404): коды 5xx
    и клиентские таймауты, которые Prometheus не фиксирует (см. §3.1 ВКР)."""
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log(f"[!] не удалось прочитать сводку k6: {summary_path}")
        return {}
    metrics = data.get("metrics", {})
    total = metrics.get("http_reqs", {}).get("count")
    checks = metrics.get("checks", {})
    passed = checks.get("passes", 0)
    failed = checks.get("fails", 0)
    denom = passed + failed
    error_rate = failed / denom if denom else 0.0
    log(f"k6: всего запросов {total}, ошибок {failed} ({error_rate * 100:.1f}%)")
    return {"total": total, "failed": failed, "error_rate": error_rate}


def query_prometheus_range(query: str, start: float, end: float, step: str = "15s"):
    """Выполняет диапазонный запрос к Prometheus."""
    try:
        r = requests.get(
            f"{PROMETHEUS_HOST}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=60,
        )
        return r.json().get("data", {}).get("result", [])
    except Exception as e:
        log(f"ошибка запроса к Prometheus: {e}")
        return []


def find_capacity(start: float, end: float) -> dict:
    """Анализирует временные ряды Prometheus и находит ёмкость (макс. запросов/с на пороге SLO)."""

    # 95-й процентиль по всем эндпоинтам (с учётом реального состава запросов)
    p95_query = (
        'histogram_quantile(0.95, '
        'sum by (le) (rate(rec_request_duration_seconds_bucket[30s])))'
    )
    p95_results = query_prometheus_range(p95_query, start, end)

    p95_rec_series = p95_results[0].get("values", []) if p95_results else None
    if not p95_rec_series:
        log("[!] серверный p95 пуст (сервис мог онеметь под перегрузом) - опираемся на k6")

    # Запросов в секунду по времени
    rps_query = 'sum(rate(rec_requests_total[30s]))'
    rps_results = query_prometheus_range(rps_query, start, end)
    rps_series = rps_results[0].get("values", []) if rps_results else []

    # Загрузка процессора по времени
    cpu_query = 'rate(process_cpu_seconds_total{job="rec-service"}[30s])'
    cpu_results = query_prometheus_range(cpu_query, start, end)
    cpu_series = cpu_results[0].get("values", []) if cpu_results else []

    # Потребление памяти по времени
    ram_query = 'process_resident_memory_bytes{job="rec-service"}'
    ram_results = query_prometheus_range(ram_query, start, end)
    ram_series = ram_results[0].get("values", []) if ram_results else []

    # 99-й процентиль по всем эндпоинтам
    p99_query = (
        'histogram_quantile(0.99, '
        'sum by (le) (rate(rec_request_duration_seconds_bucket[30s])))'
    )
    p99_results = query_prometheus_range(p99_query, start, end)
    p99_rec_series = p99_results[0].get("values", []) if p99_results else None

    # Доля попаданий в кэш по времени
    cache_hits_query = 'sum(rate(rec_cache_hits_total[30s]))'
    cache_misses_query = 'sum(rate(rec_cache_misses_total[30s]))'
    hits_results = query_prometheus_range(cache_hits_query, start, end)
    misses_results = query_prometheus_range(cache_misses_query, start, end)
    hits_series = hits_results[0].get("values", []) if hits_results else []
    misses_series = misses_results[0].get("values", []) if misses_results else []

    # Уникальные пользователи за прогон (метрика приложения, снимается как кэш-хиты).
    # Счётчик монотонно растёт, поэтому берём максимум по ряду.
    uniq_results = query_prometheus_range("rec_unique_users", start, end)
    uniq_series = uniq_results[0].get("values", []) if uniq_results else []
    unique_users = int(max((float(v) for _, v in uniq_series), default=0))

    def first_series(query: str):
        res = query_prometheus_range(query, start, end)
        return res[0].get("values", []) if res else []

    # CPU и память всей машины (node-exporter): нужны для подтверждения, что
    # хост не перегружен и числа воспроизводимы между стендами.
    host_cpu_series = first_series(
        '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[30s]))) * 100')
    host_ram_series = first_series(
        '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / 1048576')
    # Steal time: доля процессора, отнятая гипервизором у соседей по хосту.
    # Около нуля -> ядра фактически выделенные, числа чистые. Заметный steal ->
    # стенд шумный (общие vCPU), результатам верить нельзя.
    host_steal_series = first_series(
        'avg(rate(node_cpu_seconds_total{mode="steal"}[30s])) * 100')

    # CPU и память по контейнерам (cAdvisor): db, redis, rec-service.
    # Перекрёстная проверка лимитов cgroup и поиск, кто упирается в потолок.
    CONTAINERS = {
        "db": "compose-db-1",
        "redis": "compose-redis-1",
        "rec-service": "compose-rec-service-1",
    }
    cont_cpu_series = {}
    cont_ram_series = {}
    for short, name in CONTAINERS.items():
        cont_cpu_series[short] = first_series(
            f'rate(container_cpu_usage_seconds_total{{name="{name}"}}[30s]) * 100')
        cont_ram_series[short] = first_series(
            f'container_memory_usage_bytes{{name="{name}"}} / 1048576')

    # Клиентские метрики k6: истинный rps нагрузки и доля ошибок. k6 видит КАЖДЫЙ
    # запрос, включая таймауты, тогда как серверная гистограмма под перегрузом
    # "немеет". Ошибка = всё, кроме статусов 200 и 404 (404 = "нет похожих", не ошибка).
    k6_total_series = first_series('sum(rate(k6_http_reqs_total[30s]))')
    k6_ok_series = first_series('sum(rate(k6_http_reqs_total{status="200"}[30s]))')
    k6_404_series = first_series('sum(rate(k6_http_reqs_total{status="404"}[30s]))')

    # Сборка согласованных по времени рядов
    # Индексируем rps/cpu/ram по метке времени для поиска
    def to_dict(series):
        return {float(ts): float(val) for ts, val in series}

    rps_map = to_dict(rps_series)
    cpu_map = to_dict(cpu_series)
    ram_map = to_dict(ram_series)
    p95_map = to_dict(p95_rec_series) if p95_rec_series else {}
    p99_map = to_dict(p99_rec_series) if p99_rec_series else {}
    hits_map = to_dict(hits_series)
    misses_map = to_dict(misses_series)
    k6_total_map = to_dict(k6_total_series)
    k6_ok_map = to_dict(k6_ok_series)
    k6_404_map = to_dict(k6_404_series)

    host_cpu_map = to_dict(host_cpu_series)
    host_ram_map = to_dict(host_ram_series)
    host_steal_map = to_dict(host_steal_series)
    cont_cpu_map = {k: to_dict(v) for k, v in cont_cpu_series.items()}
    cont_ram_map = {k: to_dict(v) for k, v in cont_ram_series.items()}

    def closest(mapping, ts):
        if not mapping:
            return None
        closest_ts = min(mapping.keys(), key=lambda k: abs(k - ts))
        if abs(closest_ts - ts) < 30:
            return mapping[closest_ts]
        return None

    if not k6_total_series:
        log("[!] нет данных k6 в Prometheus (remote-write не работает?)")
        return {"capacity_rps": 0, "error": "нет данных k6"}

    # Спайн таймлайна - ряд k6 (он есть всегда, даже когда сервис "онемел").
    # SLO: ошибки<1% И p95<500 И p99<1000. Отсутствие серверного p95 (сервис под
    # перегрузом перестал отвечать) трактуем как срыв SLO.
    MIN_RPS = 5  # точки с почти нулевой нагрузкой ёмкостью не считаем
    last_good = None
    breach_point = None
    timeline = []

    for ts_str, total_str in k6_total_series:
        ts = float(ts_str)
        k6_rps = float(total_str)
        ok = closest(k6_ok_map, ts) or 0.0
        n404 = closest(k6_404_map, ts) or 0.0
        # доля ошибок = всё, кроме 200 и 404 (таймауты + 5xx)
        k6_err = max(0.0, (k6_rps - ok - n404) / k6_rps) if k6_rps > 0 else None

        p95 = closest(p95_map, ts)
        p99 = closest(p99_map, ts)
        p95_ms = p95 * 1000 if p95 is not None else None
        p99_ms = p99 * 1000 if p99 is not None else None
        cpu = closest(cpu_map, ts)
        ram = closest(ram_map, ts)
        hits = closest(hits_map, ts)
        misses = closest(misses_map, ts)
        cache_hit_pct = None
        if hits is not None and misses is not None and (hits + misses) > 0:
            cache_hit_pct = hits / (hits + misses) * 100

        point = {
            "ts": ts,
            "rps": k6_rps,
            "error_pct": k6_err * 100 if k6_err is not None else None,
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
            "cpu_pct": cpu * 100 if cpu else None,
            "ram_mb": ram / (1024 * 1024) if ram else None,
            "cache_hit_pct": cache_hit_pct,
        }
        timeline.append(point)

    # SLO точки: ошибки<1% И p95<500 (есть данные) И p99<1000
    def slo_ok(p):
        return (p["error_pct"] is not None and p["error_pct"] < 1.0
                and p["p95_ms"] is not None and p["p95_ms"] < SLO_P95
                and (p["p99_ms"] is None or p["p99_ms"] < SLO_P99))

    # Устойчивый срыв: первая из ДВУХ подряд нарушающих SLO точек. Одиночный
    # всплеск (соседи в норме) - шум, ёмкость не обрезает. Ёмкость = макс. rps
    # среди исправных точек ДО устойчивого срыва.
    pts = [p for p in timeline if p["rps"] > MIN_RPS]
    breach_idx = None
    for i in range(len(pts) - 1):
        if not slo_ok(pts[i]) and not slo_ok(pts[i + 1]):
            breach_idx = i
            break

    saturated = breach_idx is not None
    pool = pts[:breach_idx] if saturated else pts
    good_pts = [p for p in pool if slo_ok(p)]
    last_good = max(good_pts, key=lambda p: p["rps"]) if good_pts else None
    breach_point = pts[breach_idx] if saturated else None
    capacity_rps = int(last_good["rps"]) if last_good else 0

    log(f"Ёмкость: {capacity_rps} запросов/с" + ("" if saturated
        else "  [!] рампа НЕ сломала сервис - max-rps мал, ёмкость занижена (нижняя граница)"))
    if last_good:
        log("  При ёмкости: rps={:.0f}, p95={:.0f}мс, p99={:.0f}мс, ошибки={:.2f}%, CPU={:.0f}%, RAM={:.0f}МБ{}".format(
            last_good["rps"], last_good["p95_ms"] or 0, last_good["p99_ms"] or 0,
            last_good["error_pct"] or 0, last_good["cpu_pct"] or 0, last_good["ram_mb"] or 0,
            ", кэш={:.0f}%".format(last_good["cache_hit_pct"]) if last_good.get("cache_hit_pct") is not None else ""))
    if breach_point:
        log("  Точка срыва: rps={:.0f}, p95={}, ошибки={:.1f}%".format(
            breach_point["rps"],
            "{:.0f}мс".format(breach_point["p95_ms"]) if breach_point["p95_ms"] is not None else "нет данных (сервис онемел)",
            breach_point["error_pct"] or 0))

    # Ресурсы хоста и контейнеров: значения в точке ёмкости и пики за весь прогон
    def at_ts(mapping):
        return closest(mapping, last_good["ts"]) if last_good else None

    def peak(mapping):
        return max(mapping.values()) if mapping else None

    resources = {
        "at_capacity": {
            "host_cpu_pct": at_ts(host_cpu_map),
            "host_ram_mb": at_ts(host_ram_map),
            "host_steal_pct": at_ts(host_steal_map),
            "containers": {
                short: {"cpu_pct": at_ts(cont_cpu_map[short]),
                        "ram_mb": at_ts(cont_ram_map[short])}
                for short in CONTAINERS
            },
        },
        "peak": {
            "host_cpu_pct": peak(host_cpu_map),
            "host_ram_mb": peak(host_ram_map),
            "host_steal_pct": peak(host_steal_map),
            "containers": {
                short: {"cpu_pct": peak(cont_cpu_map[short]),
                        "ram_mb": peak(cont_ram_map[short])}
                for short in CONTAINERS
            },
        },
    }

    rc = resources["at_capacity"]
    if rc["host_cpu_pct"] is not None:
        steal_peak = resources["peak"]["host_steal_pct"]
        log(f"  Хост при ёмкости: CPU={rc['host_cpu_pct']:.0f}%, RAM={rc['host_ram_mb']:.0f}МБ"
            + (f", steal пик={steal_peak:.1f}%" if steal_peak is not None else ""))
    for short in CONTAINERS:
        c = rc["containers"][short]
        if c["cpu_pct"] is not None:
            log(f"    {short}: CPU={c['cpu_pct']:.0f}%, RAM={c['ram_mb']:.0f}МБ")

    return {
        "capacity_rps": capacity_rps,
        "saturated": saturated,  # сломала ли рампа сервис; False -> max-rps мал, ёмкость занижена
        "at_capacity": last_good,
        "breach_point": breach_point,
        "unique_users": unique_users,
        "resources": resources,
        "timeline_points": len(timeline),
        "timeline": timeline,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("lang", choices=["python", "go"])
    parser.add_argument("--iter", type=int, choices=sorted(ITER_DIRS.keys()),
                        required=True, dest="iteration")
    parser.add_argument("--suffix", type=str, default="")
    parser.add_argument("--max-rps", type=int, default=800)
    parser.add_argument("--duration", type=str, default="15m")
    args = parser.parse_args()

    wait_health()

    iter_name = ITER_DIRS[args.iteration]
    dir_name = "breakpoint" if not args.suffix else f"breakpoint-{args.suffix}"
    out_dir = RESULTS_ROOT / iter_name / args.lang / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "k6_summary.json"

    start, end = run_k6_ramp(args.max_rps, args.duration, summary_path)

    # Ждём, пока Prometheus соберёт последние данные
    time.sleep(5)

    result = find_capacity(start, end)
    result["lang"] = args.lang
    result["iteration"] = args.iteration
    result["suffix"] = args.suffix
    result["max_rps"] = args.max_rps
    result["duration"] = args.duration
    result["slo"] = {"p95_ms": SLO_P95, "p99_ms": SLO_P99}
    # Общее число запросов и доля ошибок из сводки k6 (Prometheus их не видит)
    result["requests"] = parse_k6_summary(summary_path)
    result["timestamp"] = dt.datetime.now().isoformat()

    out_path = out_dir / "breakpoint.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    log(f"Сохранено: {out_path}")


if __name__ == "__main__":
    main()
