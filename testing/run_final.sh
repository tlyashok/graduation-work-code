#!/bin/bash
# ЕДИНЫЙ финальный прогон эталонного стенда. Делает весь эксперимент и готовит
# данные в удобном для ознакомления виде (HTML-отчёт), а не только в сыром.
#
# Этапы:
#   1) Ёмкость: 4 прогона всех 8 конфигураций (медиана + повторяемость).
#   2) Профили по ИТЕРАЦИЯМ: диаграмма пламени приложения (py-spy/pprof) И чистый
#      профиль СУБД pg_stat (со сбросом перед нагрузкой) — на каждой итерации,
#      чтобы видеть, что оптимизировать дальше.
#   3) HTML-отчёт results/report/index.html — таблицы, графики, диаграммы пламени,
#      профили БД по итерациям, планы EXPLAIN.
#
# Запуск:
#   nohup bash testing/run_final.sh > run_final.log 2>&1 < /dev/null &
set -u

TESTING="$(cd "$(dirname "$0")" && pwd)"
cd "$TESTING"
log() { echo "=== $* $(date '+%F %T') ==="; }

# --- Зависимости (идемпотентно) ---
log "Установка зависимостей (go, graphviz, matplotlib, perl)"
apt-get install -y -qq golang-go graphviz python3-matplotlib python3-numpy perl \
    2>/dev/null || echo "[!] часть зависимостей не поставилась — проверь отчёт/Go-профили"
# flamegraph.pl для построения Go-флеймов (profile.py)
if [ ! -f tools/flamegraph.pl ]; then
    curl -s -o tools/flamegraph.pl \
        https://raw.githubusercontent.com/brendangregg/FlameGraph/master/flamegraph.pl \
        && chmod +x tools/flamegraph.pl && echo "flamegraph.pl загружен"
fi

# --- 1. Ёмкость: 4 прогона ---
log "ЁМКОСТЬ: 4 прогона (run_passes.sh)"
bash run_passes.sh 4
PASS_RC=$?
log "ЁМКОСТЬ завершена rc=$PASS_RC"

if [ "$PASS_RC" -ne 0 ]; then
    log "ЁМКОСТЬ упала (rc=$PASS_RC) — профили/демо/отчёт пропущены"
    exit "$PASS_RC"
fi

# --- 2. Профили по итерациям (приложение + БД) ---
log "ПРОФИЛИ по итерациям (приложение + pg_stat)"
bash run_all_profiles.sh
log "ПРОФИЛИ завершены rc=$?"

# --- HTML-отчёт ---
log "ОТЧЁТ (build_report.py)"
if python3 -c "import matplotlib" 2>/dev/null; then
    python3 analysis/build_report.py --out results/report
    log "ОТЧЁТ готов: results/report/index.html (rc=$?)"
else
    echo "[!] matplotlib отсутствует — отчёт собрать на стенде нельзя."
    echo "    Данные сохранены в results/; собери отчёт локально:"
    echo "    python testing/analysis/build_report.py --out results/report"
fi

log "ФИНАЛЬНЫЙ ПРОГОН ЗАВЕРШЁН"
