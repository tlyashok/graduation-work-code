#!/bin/bash
# N чистых пассов (повторяемость на одном стенде): каждый - полный свип всех 8
# конфигураций; после каждого результаты снимаются в results/passN/ (чтобы
# следующий пасс не затёр). Постобработка считает медиану и разброс по пассам.
#
# Запуск: bash run_passes.sh [N]   (по умолчанию 4)
set -u

TESTING="$(cd "$(dirname "$0")" && pwd)"
RESULTS="$TESTING/results"
N="${1:-4}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

for PASS in $(seq 1 "$N"); do
    log "================= ПАСС $PASS/$N ================="
    bash "$TESTING/run_all_breakpoints.sh"
    rc=$?
    log "пасс $PASS завершён (rc=$rc), снимаю в results/pass$PASS"

    DEST="$RESULTS/pass$PASS"
    rm -rf "$DEST"; mkdir -p "$DEST"
    ( cd "$RESULTS" && find . -path "./pass*" -prune -o \
        \( -name "breakpoint.json" -o -name "k6_summary.json" \) -print | while read -r f; do
            mkdir -p "$DEST/$(dirname "$f")"
            cp "$f" "$DEST/$f"
        done )
    # планы EXPLAIN (детерминированы, снимаем копию для протокола пасса)
    [ -d "$RESULTS/explain" ] && cp -r "$RESULTS/explain" "$DEST/explain" 2>/dev/null || true
    log "снимок пасса $PASS готов"
done

log "================= ВСЕ $N ПАССА ГОТОВЫ ================="
