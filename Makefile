.PHONY: up down logs ps migrate sync lint test demo-m1 \
	migrate-native run-native stop-native logs-native demo-native \
	run-mock-api-native run-devops-api-native demo-m2 demo-m2-devops \
	stop-mcp-native restart-mcp-native demo-m3 \
	run-worker-native up-langfuse down-langfuse demo-m4 demo-m5

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

run-mock-api-native:
	mkdir -p .run
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run python demo/mock_api/main.py \
		> .run/mock-api.log 2>&1 & echo $$! > .run/mock-api.pid
	@echo "mock-api pid $$(cat .run/mock-api.pid), log: .run/mock-api.log"

run-devops-api-native:
	mkdir -p .run
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run python demo/mock_devops_api/main.py \
		> .run/devops-api.log 2>&1 & echo $$! > .run/devops-api.pid
	@echo "devops-api pid $$(cat .run/devops-api.pid), log: .run/devops-api.log"

stop-native:
	-kill $$(cat .run/orchestrator-api.pid) 2>/dev/null
	-kill $$(cat .run/mcp-server.pid) 2>/dev/null
	-kill $$(cat .run/mock-api.pid) 2>/dev/null
	-kill $$(cat .run/devops-api.pid) 2>/dev/null
	-kill $$(cat .run/orchestrator-worker.pid) 2>/dev/null
	rm -f .run/orchestrator-api.pid .run/mcp-server.pid .run/mock-api.pid .run/devops-api.pid .run/orchestrator-worker.pid

logs-native:
	tail -f .run/orchestrator-api.log .run/mcp-server.log .run/mock-api.log .run/devops-api.log .run/orchestrator-worker.log

demo-native:
	curl -sf http://localhost:8000/healthz && echo "\norchestrator-api OK"

demo-m2: run-mock-api-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m2_register_tool_and_call.py

demo-m2-devops: run-devops-api-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m2_devops_tools_and_call.py

stop-mcp-native:
	-kill $$(cat .run/mcp-server.pid) 2>/dev/null
	rm -f .run/mcp-server.pid

restart-mcp-native: stop-mcp-native
	mkdir -p .run
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run python -m mcp_server.server \
		> .run/mcp-server.log 2>&1 & echo $$! > .run/mcp-server.pid
	@echo "mcp-server restarted, pid $$(cat .run/mcp-server.pid)"

demo-m3: run-mock-api-native run-devops-api-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m3_register_openapi_sources.py
	$(MAKE) restart-mcp-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m3_openapi_adapter_demo.py

# --- M4: LangGraph agent runtime. Needs Redis (native, e.g. `sudo systemctl
# start redis-server`) and Langfuse (self-hosted via Docker below, or
# Langfuse Cloud) in addition to everything M1-M3 already needs. ---

up-langfuse:
	docker compose -f infra/docker-compose/docker-compose.langfuse.yml up -d

down-langfuse:
	docker compose -f infra/docker-compose/docker-compose.langfuse.yml down

run-worker-native:
	mkdir -p .run
	set -a; [ -f .env ] && . ./.env; set +a; \
	nohup uv run arq orchestrator_worker.worker.WorkerSettings \
		> .run/orchestrator-worker.log 2>&1 & echo $$! > .run/orchestrator-worker.pid
	@echo "orchestrator-worker pid $$(cat .run/orchestrator-worker.pid), log: .run/orchestrator-worker.log"

demo-m4: run-mock-api-native run-devops-api-native run-worker-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m4_langgraph_agent_demo.py

# --- M5: model registry + multi-provider routing. No new infra vs M4 — the
# registry is read fresh from Postgres on every run, so no service restart
# is needed after (re-)registering providers/models/routing rules. ---

demo-m5: run-mock-api-native run-devops-api-native run-worker-native
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m5_register_model_providers.py
	set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python demo/scripts/m5_multi_model_routing_demo.py
