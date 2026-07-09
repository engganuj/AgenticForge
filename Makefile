.PHONY: up down logs ps migrate sync lint test demo-m1 \
	migrate-native run-native stop-native logs-native demo-native

COMPOSE = docker compose -f infra/docker-compose/docker-compose.yml
COMPOSE_ALL = $(COMPOSE) -f infra/docker-compose/docker-compose.langfuse.yml

up:
	$(COMPOSE_ALL) up --build -d

down:
	$(COMPOSE_ALL) down

logs:
	$(COMPOSE_ALL) logs -f

ps:
	$(COMPOSE_ALL) ps

migrate:
	$(COMPOSE) run --rm migrate

sync:
	uv sync --all-packages --group dev

lint:
	uv run ruff check .

test:
	uv run pytest

demo-m1:
	curl -sf http://localhost:8000/healthz && echo "\norchestrator-api OK"
	curl -sf http://localhost:3000/api/public/health && echo "\nlangfuse OK"

# --- Native (no Docker) mode: run against an existing Postgres, no Redis/Langfuse required for M1 ---

migrate-native:
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run --group dev alembic -c migrations/alembic.ini upgrade head

run-native:
	mkdir -p .run
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run uvicorn orchestrator_api.main:app --host 0.0.0.0 --port 8000 \
		> .run/orchestrator-api.log 2>&1 & echo $$! > .run/orchestrator-api.pid
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run python -m mcp_server.server \
		> .run/mcp-server.log 2>&1 & echo $$! > .run/mcp-server.pid
	@echo "orchestrator-api pid $$(cat .run/orchestrator-api.pid), log: .run/orchestrator-api.log"
	@echo "mcp-server pid $$(cat .run/mcp-server.pid), log: .run/mcp-server.log"

stop-native:
	-kill $$(cat .run/orchestrator-api.pid) 2>/dev/null
	-kill $$(cat .run/mcp-server.pid) 2>/dev/null
	rm -f .run/orchestrator-api.pid .run/mcp-server.pid

logs-native:
	tail -f .run/orchestrator-api.log .run/mcp-server.log

demo-native:
	curl -sf http://localhost:8000/healthz && echo "\norchestrator-api OK"
