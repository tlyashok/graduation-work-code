#!/usr/bin/env bash
# ============================================================
# Развёртывание стенда.
# Ставит Docker + k6 + зависимости, готовит .env, заполняет MovieLens 25M
# и считает модель сходства. После запускать testing/run_final.sh.
#
# Запуск из корня репозитория:
#     sudo bash testing/cloud/bootstrap.sh
# ============================================================
set -euo pipefail

K6_VERSION="v0.49.0"

log() { echo "[$(date +%H:%M:%S)] $*"; }

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
log "Корень репозитория: $REPO_ROOT"

# --- 1. Системные пакеты ---
log "Установка системных пакетов..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-requests make git curl ca-certificates tar

# --- 2. Docker (официальный скрипт ставит движок + плагин compose) ---
if ! command -v docker >/dev/null 2>&1; then
    log "Установка Docker..."
    curl -fsSL https://get.docker.com | sh
else
    log "Docker уже установлен: $(docker --version)"
fi

if ! grep -q registry-mirrors /etc/docker/daemon.json 2>/dev/null; then
    log "Настройка зеркала Docker Hub..."
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": ["https://dockerhub.timeweb.cloud", "https://huecker.io"]
}
EOF
    systemctl restart docker
    sleep 5
fi

# --- 3. k6 (бинарь в PATH; run_breakpoint.py найдёт через which) ---
if ! command -v k6 >/dev/null 2>&1; then
    log "Установка k6 ${K6_VERSION}..."
    tmp="$(mktemp -d)"
    curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-amd64.tar.gz" \
        | tar xz -C "$tmp"
    install "$tmp"/k6-*/k6 /usr/local/bin/k6
    rm -rf "$tmp"
else
    log "k6 уже установлен: $(k6 version)"
fi
log "k6: $(command -v k6)"

# --- 4. .env для трёх итераций (из .env.example, без перезаписи) ---
for d in 0-baseline 1-async-pooling 2-redis-cache; do
    if [ ! -f "deploy/$d/.env" ]; then
        cp "deploy/$d/.env.example" "deploy/$d/.env"
        log ".env создан: $d"
    fi
done

# --- 5. Каталоги под bind-mount nginx и результаты ---
mkdir -p testing/logs/nginx testing/results

# --- 6. Наполнение MovieLens 25M + расчёт модели сходства (один раз) ---
# Все три итерации используют имя проекта compose -> общие volume
# compose_pgdata и compose_movielens-data. Сеем один раз из любой итерации.
if docker volume inspect compose_pgdata >/dev/null 2>&1 \
   && [ "$(docker run --rm -v compose_pgdata:/v alpine sh -c 'ls /v 2>/dev/null | wc -l')" != "0" ]; then
    log "Volume compose_pgdata уже существует и непуст - посев пропущен."
else
    log "Посев MovieLens 25M + расчёт модели (30-50 мин, скачивает ~250 МБ)..."
    ( cd deploy/2-redis-cache && make init )
    log "Посев завершён."
fi

# --- 7. Параметры запросов для k6 (testing/data/k6_params.json) ---
# Сценарии k6 читают пары (user_id, movie_id) из этого файла; он генерируется
# из ratings.csv с сохранением распределения активности пользователей.
if [ ! -f testing/data/k6_params.json ]; then
    log "Генерация параметров запросов для k6..."
    mkdir -p testing/data
    docker run --rm -v compose_movielens-data:/data -v "$REPO_ROOT/testing/data:/out" \
        alpine cp "/data/${MOVIELENS_DATASET:-ml-25m}/ratings.csv" /out/ratings.csv
    python3 testing/generate_params.py
    rm -f testing/data/ratings.csv
fi

log "ГОТОВО. Полный прогон: cd testing && bash run_final.sh"
