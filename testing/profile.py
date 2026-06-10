"""
Профилировочный прогон для построения пламенного графика (§3.1 ВКР).

Делается отдельно от основных нагрузочных прогонов - только при
диагностике конкретного узкого места. Для каждого языка свой инструмент:
- Python: py-spy (запускается внутри контейнера через docker exec,
  требует SYS_PTRACE - добавлено в compose);
- Go: net/http/pprof (через gin-contrib/pprof, эндпоинт
  /debug/pprof/profile?seconds=N), результат конвертируется в SVG
  через `go tool pprof`.

Использование:
  python profile.py python --iter 0 --rps 100 --duration 60
  python profile.py go     --iter 1 --rps 100 --duration 60

Перед запуском должна быть поднята нужная реализация:
  cd deploy/{итерация} && make python   # или make go

Артефакты:
  testing/results/profiles/{итерация}/{python,go}/{timestamp}/
    profile.svg            - пламенный график
    profile.raw            - исходные данные профилировщика
    (k6 в фоне создаёт нагрузку; отдельных файлов не сохраняется)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    return "k6"


K6_BIN = _k6_bin()
K6_SCRIPT = REPO_ROOT / "testing" / "k6" / "loadtest.js"
RESULTS_ROOT = REPO_ROOT / "testing" / "results"
REC_SERVICE_HOST = "http://127.0.0.1:8000"
CONTAINER = "compose-rec-service-1"

# Каталоги deploy по номеру итерации (синхронно с run_breakpoint.py).
ITER_DIRS = {
    0: "0-baseline",
    1: "1-async-pooling",
    2: "2-redis-cache",
}


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def profile_python(out_dir: Path, duration: int) -> None:
    """py-spy внутри контейнера: профиль в формате SVG."""
    raw_inside = "/tmp/profile.svg"
    log(f"py-spy record (PID 1, {duration}s) внутри {CONTAINER}...")
    subprocess.run(
        [
            "docker", "exec", CONTAINER,
            "py-spy", "record",
            "-o", raw_inside,
            "--pid", "1",
            "--duration", str(duration),
            "--format", "flamegraph",
        ],
        check=True,
    )
    subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{raw_inside}", str(out_dir / "profile.svg")],
        check=True,
    )
    log(f"SVG: {out_dir / 'profile.svg'}")


TOOLS_DIR = Path(__file__).resolve().parent / "tools"
FOLD_SCRIPT = Path(__file__).resolve().parent / "fold_traces.py"
FLAMEGRAPH_PL = TOOLS_DIR / "flamegraph.pl"


def profile_go(out_dir: Path, duration: int) -> None:
    """Снятие профиля pprof и сборка ДИАГРАММЫ ПЛАМЕНИ (для согласованности с
    py-spy). Конвейер: go tool pprof -traces -> свёртка стеков -> flamegraph.pl.
    Если perl/flamegraph.pl недоступны, откат на граф вызовов (go tool pprof -svg)."""
    raw_path = out_dir / "profile.raw"
    svg_path = out_dir / "profile.svg"

    log(f"curl /debug/pprof/profile?seconds={duration}...")
    subprocess.run(
        [
            "curl", "-s", "-o", str(raw_path),
            f"{REC_SERVICE_HOST}/debug/pprof/profile?seconds={duration}",
        ],
        check=True,
    )

    if not shutil.which("go"):
        log("[!] в PATH нет go: SVG не построен, сырой профиль в profile.raw.")
        return

    can_flame = (shutil.which("perl") and FLAMEGRAPH_PL.exists() and FOLD_SCRIPT.exists())
    if can_flame:
        log("go tool pprof -traces -> fold -> flamegraph.pl (диаграмма пламени)")
        traces = subprocess.run(["go", "tool", "pprof", "-traces", str(raw_path)],
                                 capture_output=True, text=True).stdout
        folded = subprocess.run([sys.executable, str(FOLD_SCRIPT)],
                                input=traces, capture_output=True, text=True).stdout
        title = f"pprof CPU flame graph (Go, {out_dir.parents[1].name})"
        with open(svg_path, "w", encoding="utf-8") as f:
            r = subprocess.run(
                ["perl", str(FLAMEGRAPH_PL), "--title", title,
                 "--width", "1600", "--colors", "hot", "--hash"],
                input=folded, text=True, stdout=f,
            )
        if r.returncode == 0 and svg_path.stat().st_size > 0:
            log(f"SVG (флейм): {svg_path}")
            return
        log("[!] flamegraph.pl не справился, откат на граф вызовов")

    log(f"go tool pprof -svg (граф вызовов) -> {svg_path}")
    with open(svg_path, "wb") as f:
        subprocess.run(["go", "tool", "pprof", "-svg", str(raw_path)], check=True, stdout=f)
    log(f"SVG: {svg_path}")


def run_load(rps: int, duration: int, out_prefix: Path) -> subprocess.Popen:
    """Запускает k6 в фоне: постоянная нагрузка на duration+10 секунд для съёма профиля."""
    log(f"k6 в фоне: {rps} запросов/с, {duration + 10} с")
    return subprocess.Popen(
        [
            str(K6_BIN), "run",
            "--env", f"RPS={rps}",
            "--env", f"DURATION={duration + 10}s",
            "--env", f"BASE_URL={REC_SERVICE_HOST}",
            "--quiet",
            str(K6_SCRIPT),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("lang", choices=["python", "go"])
    parser.add_argument("--iter", type=int, choices=sorted(ITER_DIRS.keys()), default=0,
                        dest="iteration",
                        help="номер итерации оптимизации (0, 1, 2 - см. §2.5)")
    parser.add_argument("--rps", type=int, default=100,
                        help="число запросов в секунду при профилировании")
    parser.add_argument("--duration", type=int, default=60,
                        help="длительность профилирования (секунды)")
    args = parser.parse_args()

    iter_name = ITER_DIRS[args.iteration]
    timestamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = RESULTS_ROOT / "profiles" / iter_name / args.lang / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    load_proc = run_load(args.rps, args.duration, out_dir / "load")
    log("Ждём 5 секунд, чтобы нагрузка раскрутилась...")
    time.sleep(5)

    try:
        if args.lang == "python":
            profile_python(out_dir, args.duration)
        else:
            profile_go(out_dir, args.duration)
    finally:
        log("Ждём завершения k6...")
        load_proc.wait(timeout=args.duration + 60)

    log("=" * 60)
    log(f"ГОТОВО: {out_dir}")
    log("=" * 60)


if __name__ == "__main__":
    main()
