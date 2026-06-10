#!/bin/bash
# Последовательный прогон всех тестов ёмкости.
# Запуск: bash run_all_breakpoints.sh

set -e

DEPLOY="$(cd "$(dirname "$0")/../deploy" && pwd)"
TESTING="$(cd "$(dirname "$0")" && pwd)"
# k6 вызывает run_breakpoint.py; путь определяется там (K6_BIN / PATH / ~/bin)

log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_health() {
    for i in $(seq 1 60); do
        if python3 "$TESTING/wait_health.py" 2>/dev/null; then return 0; fi
        sleep 3
    done
    echo "ПРЕВЫШЕНО ВРЕМЯ ОЖИДАНИЯ ГОТОВНОСТИ"; return 1
}

run_iter() {
    local ITER_NUM="$1" DEPLOY_DIR="$2" LANG="$3" MAX_RPS="$4" DURATION="$5" SUFFIX="$6"
    log "=== Итерация $ITER_NUM $LANG (макс=$MAX_RPS, длит=$DURATION) ==="

    cd "$DEPLOY/$DEPLOY_DIR"
    docker compose --env-file .env -f compose/infra.yml -f compose/python.yml -f compose/go.yml down 2>/dev/null || true
    sleep 2
    make "$LANG"
    cd "$TESTING"
    wait_health

    # Сброс Redis для итерации 2
    if [ "$ITER_NUM" = "2" ]; then
        docker exec compose-redis-1 redis-cli FLUSHALL || true
    fi

    # Удаление индексов для итерации 0 (baseline без индексов)
    if [ "$ITER_NUM" = "0" ]; then
        docker exec compose-db-1 psql -U filmrec -d filmrec -c "DROP INDEX IF EXISTS idx_ratings_user_id; DROP INDEX IF EXISTS idx_movies_popularity;" || true
    fi

    local ARGS="$LANG --iter $ITER_NUM --max-rps $MAX_RPS --duration $DURATION"
    if [ -n "$SUFFIX" ]; then ARGS="$ARGS --suffix $SUFFIX"; fi

    python3 run_breakpoint.py $ARGS
    log "=== Готово: итерация $ITER_NUM $LANG ==="
}

set_ttl() {
    local TTL="$1"
    cd "$DEPLOY/2-redis-cache"
    sed -i "s/CACHE_TTL_SECONDS=[0-9]*/CACHE_TTL_SECONDS=$TTL/" .env
    log "TTL set to $TTL"
}

# max-rps откалиброваны под РЕАЛЬНЫЕ потолки (клиентский метод k6): Python упирается
# в своё ядро, Go - в БД (4 ядра). Берём ~1.6x потолка, чтобы рампа дошла до срыва;
# флаг saturated в breakpoint.json подтверждает, что сервис реально сломан.

# --- Итерация 0 (без индекса - коллапс, потолок ~1) ---
run_iter 0 0-baseline python 30 4m
python3 capture_explain.py iter0    # стек итерации 0 поднят, индекса нет
run_iter 0 0-baseline go 30 4m

# --- Итерация 1 (с индексом /popular: Python ~270 сервис-bound, Go ~2000 сервис-bound) ---
run_iter 1 1-async-pooling python 450 6m
python3 capture_explain.py iter1    # индексы созданы; снимаем EXPLAIN user+popular + pg_stat
run_iter 1 1-async-pooling go 2800 6m

# --- Итерация 2а (TTL=60; Python обвал ~165, Go сервис-bound ~3200) ---
set_ttl 60
run_iter 2 2-redis-cache python 400 6m ttl60
run_iter 2 2-redis-cache go 3800 6m ttl60

# --- Итерация 2б (TTL=600; Python обвал ~165, Go ~4000+, м.б. предел нагрузчика) ---
set_ttl 600
run_iter 2 2-redis-cache python 400 8m ttl600
run_iter 2 2-redis-cache go 4500 8m ttl600

# --- Очистка ---
set_ttl 60
cd "$DEPLOY/2-redis-cache"
docker compose --env-file .env -f compose/infra.yml -f compose/python.yml -f compose/go.yml down 2>/dev/null || true

log "=== ВСЁ ГОТОВО ==="
