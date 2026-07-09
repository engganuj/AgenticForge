# AgenticForge

Open-source enterprise agentic AI orchestration platform. This repo currently
implements **Phase 1**: the Agentic Orchestrator backend + MCP Server, built
incrementally as milestones M1-M8 (see `docs`/plan for the full breakdown).

Stack: Python, FastAPI, LangGraph, the official MCP SDK, Postgres + pgvector,
Redis, self-hosted Langfuse. Designed to run locally via Docker Compose first,
with Helm/Terraform for AWS/Azure/OKE/GCP layered on in a later phase without
architectural rework.

## Prerequisites

Native Linux (e.g. Ubuntu) or macOS — the stack is plain Docker Compose + Python:

- Docker + Docker Compose v2 (`docker compose version`)
- [`uv`](https://docs.astral.sh/uv/) for local (non-container) dev: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make`

## Quickstart

Full step-by-step setup (prerequisites, troubleshooting, verification): see [INSTALL.md](INSTALL.md).

```bash
cp .env.example .env
make up        # builds and starts postgres, redis, migrate, orchestrator-api, mcp-server, langfuse stack
make ps        # check container status
make demo-m1   # smoke-test health endpoints
```

- Orchestrator API: http://localhost:8000/healthz
- MCP server (Streamable HTTP): http://localhost:8100
- Langfuse UI: http://localhost:3000 (create the first user/org/project on
  first visit, then copy the generated public/secret key pair into `.env`)

Tear down with `make down`.

## Local (non-container) development

```bash
make sync      # uv sync --all-packages --group dev
make lint
make test
```

Migrations run automatically via the `migrate` service on `make up`. To run
them manually against a Postgres you're pointing at yourself:

```bash
DATABASE_URL=postgresql+psycopg2://agenticforge:agenticforge@localhost:5432/agenticforge \
  uv run --group dev alembic -c migrations/alembic.ini upgrade head
```

## Repository layout

```
services/orchestrator-api/     FastAPI HTTP surface (runs, agents, tools, models, admin)
services/orchestrator-worker/  LangGraph execution off a queue (built out from M4)
services/mcp-server/           MCP Streamable HTTP server + OpenAPI-to-MCP adapter
ingestion/                     File/SQL/datalake ingestion pipelines (built out from M6)
semantic-layer/cube/           Cube.dev metrics-layer definitions (built out from M7)
packages/shared/               Shared SQLAlchemy models, model registry, MCP client, RBAC
migrations/                    Alembic, single shared Postgres schema
infra/docker-compose/          Local platform topology (app stack + Langfuse stack)
demo/                          Per-milestone runnable demo scripts (double as smoke tests)
```

## Status

- [x] M1 — Skeleton: Compose stack, Postgres+pgvector, Alembic initial schema, empty orchestrator-api + MCP server
- [ ] M2 — MCP server with a manual tool + one real API
- [ ] M3 — OpenAPI-to-MCP adapter
- [ ] M4 — LangGraph agent + MCP tools, Langfuse tracing
- [ ] M5 — Model registry + multi-provider routing
- [ ] M6 — File ingestion + pgvector RAG
- [ ] M7 — Semantic layer (Cube.dev)
- [ ] M8 — RBAC/audit/PII governance hardening
