"""
Построение диаграмм ёмкости и повторяемости из breakpoint.json (4 прогона).

Эталонный стенд прогонялся 4 раза (пассы results/pass1..4). Для каждой
конфигурации берётся МЕДИАНА ёмкости по 4 пассам, а разброс (мин--макс)
служит мерой повторяемости.

Использование:
  python build_capacity_chart.py
  python build_capacity_chart.py --out-dir ../../latex/images/charts
"""

import json
import argparse
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

RESULTS_ROOT = Path(__file__).resolve().parent.parent / "results"
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "latex" / "images" / "charts"

# Конфигурация итераций: (label, dir, subdir)
ITERATIONS = [
    ("Итер. 1", "1-async-pooling", "breakpoint"),
    ("Итер. 2а\n(время жизни 60 с)", "2-redis-cache", "breakpoint-ttl60"),
    ("Итер. 2б\n(время жизни 600 с)", "2-redis-cache", "breakpoint-ttl600"),
]

LANG_COLORS = {"python": "#3572A5", "go": "#00ADD8"}


def pass_values(iter_dir: str, lang: str, subdir: str, field: str):
    """Значения поля field по всем пассам (pass1..4)."""
    vals = []
    for path in sorted(RESULTS_ROOT.glob(f"pass*/{iter_dir}/{lang}/{subdir}/breakpoint.json")):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        v = data.get(field)
        if v:
            vals.append(v)
    return vals


def at_capacity_median(iter_dir: str, lang: str, subdir: str):
    """Медианы метрик at_capacity по пассам + медиана ёмкости и разброс."""
    caps, p95s, p99s, cpus, rams, caches = [], [], [], [], [], []
    for path in sorted(RESULTS_ROOT.glob(f"pass*/{iter_dir}/{lang}/{subdir}/breakpoint.json")):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        cap = d.get("capacity_rps")
        if not cap:
            continue
        ac = d.get("at_capacity", {}) or {}
        caps.append(cap)
        if ac.get("p95_ms") is not None: p95s.append(ac["p95_ms"])
        if ac.get("p99_ms") is not None: p99s.append(ac["p99_ms"])
        if ac.get("cpu_pct") is not None: cpus.append(ac["cpu_pct"])
        if ac.get("ram_mb") is not None: rams.append(ac["ram_mb"])
        if ac.get("cache_hit_pct") is not None: caches.append(ac["cache_hit_pct"])
    med = lambda v: statistics.median(v) if v else None
    return {
        "capacity_rps": med(caps), "cap_min": min(caps) if caps else None,
        "cap_max": max(caps) if caps else None, "n": len(caps),
        "p95_ms": med(p95s), "p99_ms": med(p99s), "cpu_pct": med(cpus),
        "ram_mb": med(rams), "cache_hit_pct": med(caches),
    }


def build_capacity_bar_chart(out_dir: Path) -> None:
    """Столбчатая диаграмма ёмкости Python vs Go по итерациям (медиана 4 пассов)."""
    labels, py_vals, go_vals = [], [], []
    for label, iter_dir, subdir in ITERATIONS:
        py = at_capacity_median(iter_dir, "python", subdir)
        go = at_capacity_median(iter_dir, "go", subdir)
        if py["capacity_rps"] and go["capacity_rps"]:
            labels.append(label)
            py_vals.append(py["capacity_rps"])
            go_vals.append(go["capacity_rps"])

    x = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    bars_py = ax.bar(x - width/2, py_vals, width, label="Python", color=LANG_COLORS["python"])
    bars_go = ax.bar(x + width/2, go_vals, width, label="Go", color=LANG_COLORS["go"])

    ax.set_ylabel("Ёмкость (запросов/с)")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.legend(); ax.grid(True, alpha=0.3, axis="y")
    ax.yaxis.set_major_locator(ticker.MultipleLocator(500))
    ax.set_ylim(0, max(go_vals) * 1.12)

    for bars, is_go in ((bars_py, False), (bars_go, True)):
        for i, bar in enumerate(bars):

            prefix = "≥" if (is_go and i == len(bars) - 1) else ""
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(go_vals)*0.01,
                    prefix + str(int(round(bar.get_height()))), ha="center", va="bottom",
                    fontsize=10, fontweight="bold")

    fig.tight_layout()
    out_path = out_dir / "capacity-bars.pdf"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def build_repeatability_chart(out_dir: Path) -> None:
    """Повторяемость: ёмкость каждого из 4 пассов, нормированная на медиану конфигурации."""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    xticks, xlabels = [], []
    pos = 0
    for label, iter_dir, subdir in ITERATIONS:
        for lang in ("python", "go"):
            caps = pass_values(iter_dir, lang, subdir, "capacity_rps")
            if not caps:
                pos += 1; continue
            med = statistics.median(caps)
            ys = [c / med for c in caps]
            xs = np.full(len(ys), pos) + np.linspace(-0.12, 0.12, len(ys))
            ax.scatter(xs, ys, s=45, color=LANG_COLORS[lang], zorder=3,
                       edgecolor="white", linewidth=0.6)
            xticks.append(pos)
            short = label.replace("\n", " ").replace("Итер. ", "И").replace("время жизни ", "")
            xlabels.append(f"{'Py' if lang=='python' else 'Go'}\n{short}")
            pos += 1
        pos += 0.4

    ax.axhline(1.0, color="#444", lw=1, zorder=1)
    ax.axhspan(0.85, 1.15, color="0.85", alpha=0.5, zorder=0, label="±15 % (порог шума)")
    ax.set_ylabel("Ёмкость / медиана конфигурации")
    ax.set_xticks(xticks); ax.set_xticklabels(xlabels, fontsize=8)
    ax.set_ylim(0.6, 1.4)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    out_path = out_dir / "repeatability-passes.pdf"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def build_full_metrics_table() -> None:
    """Печатает медианные метрики при ёмкости для таблицы tab:full-metrics."""
    print("\nМедианные метрики при ёмкости (для tab:full-metrics):")
    print(f"{'Итерация':<20} {'Язык':<7} {'Ёмк':<7} {'P95':<7} {'P99':<7} {'CPU%':<7} {'RAM':<6} {'Кэш%':<6} разброс")
    print("-" * 92)
    for label, iter_dir, subdir in ITERATIONS:
        for lang in ("python", "go"):
            m = at_capacity_median(iter_dir, lang, subdir)
            if not m["capacity_rps"]:
                continue
            r = lambda v, n=0: (round(v, n) if v is not None else "н/д")
            cache = r(m["cache_hit_pct"], 1) if m["cache_hit_pct"] is not None else "н/д"
            print(f"{label.replace(chr(10),' '):<20} {('Python' if lang=='python' else 'Go'):<7} "
                  f"{r(m['capacity_rps']):<7} {r(m['p95_ms']):<7} {r(m['p99_ms']):<7} "
                  f"{r(m['cpu_pct'],1):<7} {r(m['ram_mb']):<6} {str(cache):<6} "
                  f"[{r(m['cap_min'])}..{r(m['cap_max'])}], n={m['n']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print("Диаграммы:")
    build_capacity_bar_chart(args.out_dir)
    build_repeatability_chart(args.out_dir)
    build_full_metrics_table()
    print("\nГотово.")


if __name__ == "__main__":
    main()
