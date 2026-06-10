COMPOSE = docker compose --env-file .env -f compose/infra.yml

.PHONY: python go init restart down clean logs ps help

help: ## Показать справку
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-12s %s\n", $$1, $$2}'

python: ## Поднять стек с Python rec-service
	$(COMPOSE) -f compose/python.yml up -d --build

go: ## Поднять стек с Go rec-service
	$(COMPOSE) -f compose/go.yml up -d --build

init: ## Загрузить MovieLens + вычислить модель (одноразово)
	$(COMPOSE) run --rm init

restart: ## Перезапустить rec-service (сброс кеша приложения, пулов соединений, локальных счётчиков)
	$(COMPOSE) -f compose/python.yml -f compose/go.yml restart rec-service

down: ## Остановить всё
	$(COMPOSE) -f compose/python.yml -f compose/go.yml down

clean: ## Остановить и удалить volumes (полный сброс)
	$(COMPOSE) -f compose/python.yml -f compose/go.yml down -v

logs: ## Логи (make logs s=rec-service)
	$(COMPOSE) -f compose/python.yml -f compose/go.yml logs -f $(s)

ps: ## Статус контейнеров
	$(COMPOSE) -f compose/python.yml -f compose/go.yml ps
