#!/bin/bash
# Профилировочный прогон (диаграммы пламени) — ТОЛЬКО на эталонном стенде,
# ПОСЛЕ run_all_breakpoints.sh (нужны breakpoint.json с найденной ёмкостью).
# Профили качественные (где тратится CPU), на одинаковых машинах не отличаются,
# поэтому достаточно одного стенда.
#
# Для каждой из 6 конфигураций (iter0/1/2 x python/go): поднимает стек, читает
# ёмкость, гонит нагрузку при 50% ёмкости и снимает профиль (py-spy / pprof).
#
# Требуется на стенде: Go-тулчейн (go tool pprof). Иначе Go-профиль сохранится
# сырым (profile.raw) без SVG.
#
# Запуск: bash run_all_profiles.sh

set -e

DEPLOY="$(cd "$(dirname "$0")/../deploy" && pwd)"
TESTING="$(cd "$(dirname "$0")" && pwd)"
RESULTS="$TESTING/results"

log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_health() {
    for i in $(seq 1 60); do
        if python3 "$TESTING/wait_health.py" 2>/dev/null; then return 0; fi
        sleep 3
    done
    echo "ПРЕВЫШЕНО ВРЕМЯ ОЖИДАНИЯ ГОТОВНОСТИ"; return 1
}

# Профиль снимаем при 50% от МЕДИАННОЙ ёмкости (по 4 пассам), но не выше потолка
# PROFILE_RPS_CAP: для iter2 Go медиана очень высокая (кэш), а профилирование сбрасывает
# Redis (холодный кэш) -> при 50% от тёплой ёмкости сервис захлёбывается на старте.
# Потолок держит нагрузку в безопасной зоне; на ФОРМУ флеймграфа это не влияет.
PROFILE_RPS_CAP=1500

# Медианная capacity_rps по 4 пассам для конфигурации.
read_median_capacity() {
    local iterdir="$1" lang="$2" sub="$3"
    python3 -c "
import json, statistics, glob
caps=[]
for p in sorted(glob.glob('$RESULTS/pass*/$iterdir/$lang/$sub/breakpoint.json')):
    try: c=json.load(open(p)).get('capacity_rps',0)
    except Exception: c=0
    if c: caps.append(c)
print(int(statistics.median(caps)) if caps else 0)
" 2>/dev/null || echo 0
}

# iter_num deploy_dir lang breakpoint_subdir min_rps
profile_one() {
    local ITER_NUM="$1" DEPLOY_DIR="$2" LANG="$3" SUB="$4" MIN_RPS="$5"
    log "=== Профиль: итерация $ITER_NUM $LANG ==="

    cd "$DEPLOY/$DEPLOY_DIR"
    docker compose --env-file .env -f compose/infra.yml -f compose/python.yml -f compose/go.yml down 2>/dev/null || true
    sleep 2
    make "$LANG"
    cd "$TESTING"
    wait_health

    # Сброс Redis (итер.2) / удаление индекса (итер.0) — как в прогоне ёмкости
    if [ "$ITER_NUM" = "2" ]; then
        docker exec compose-redis-1 redis-cli FLUSHALL || true
    fi
    if [ "$ITER_NUM" = "0" ]; then
        docker exec compose-db-1 psql -U filmrec -d filmrec -c "DROP INDEX IF EXISTS idx_ratings_user_id; DROP INDEX IF EXISTS idx_movies_popularity;" || true
    fi

    # Профиль при 50% ёмкости (не 75%): при 75% сервис близок к потолку, под нагрузкой
    # бывают отмены запросов -> Python жжёт CPU на логирование трейсбэков отмен, и флейм
    # забивается шумом вместо реальной работы. 50% -> отмен нет, видно настоящий профиль.
    local CAP RPS
    CAP="$(read_median_capacity "$DEPLOY_DIR" "$LANG" "$SUB")"
    RPS="$(python3 -c "print(min($PROFILE_RPS_CAP, max($MIN_RPS, round($CAP*0.5))))")"
    log "Медианная ёмкость $CAP запросов/с -> профилирование при $RPS (50%, потолок $PROFILE_RPS_CAP)"

    # Чистый по-итерационный профиль БД: сбросить pg_stat ПЕРЕД нагрузкой, снять
    # ПОСЛЕ неё (и до EXPLAIN) -> статистика отражает только нагрузку этой итерации.
    # Это даёт профиль СУБД параллельно флеймграфу приложения (та же нагрузка).
    python3 capture_explain.py reset >/dev/null 2>&1 || true

    python3 profile.py "$LANG" --iter "$ITER_NUM" --rps "$RPS" --duration 60

    python3 capture_explain.py capture "iter${ITER_NUM}_${LANG}" --out "$RESULTS/dbprofile" || true
    log "=== Готово: итерация $ITER_NUM $LANG ==="
}

set_ttl() {
    sed -i "s/CACHE_TTL_SECONDS=[0-9]*/CACHE_TTL_SECONDS=$1/" "$DEPLOY/2-redis-cache/.env"
    log "TTL=$1"
}

# --- Итерация 0 (ёмкость низкая, нижний предел нагрузки = 1 запрос/с) ---
profile_one 0 0-baseline      python breakpoint 1
profile_one 0 0-baseline      go     breakpoint 1

# --- Итерация 1 ---
profile_one 1 1-async-pooling python breakpoint 50
profile_one 1 1-async-pooling go     breakpoint 50

# --- Итерация 2 (профиль при TTL=600, как в §3.4) ---
set_ttl 600
profile_one 2 2-redis-cache   python breakpoint-ttl600 50
profile_one 2 2-redis-cache   go     breakpoint-ttl600 50

# --- Очистка ---
set_ttl 60
cd "$DEPLOY/2-redis-cache"
docker compose --env-file .env -f compose/infra.yml -f compose/python.yml -f compose/go.yml down 2>/dev/null || true

log "=== ПРОФИЛИРОВАНИЕ ЗАВЕРШЕНО ==="
log "Артефакты: $RESULTS/profiles/{0-baseline,1-async-pooling,2-redis-cache}/{python,go}/*/profile.svg"
