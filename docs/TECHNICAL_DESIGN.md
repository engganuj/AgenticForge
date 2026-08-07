# AgenticForge — Technical Design Document

## Who this is for

This document is written for developers who are new to the project — and
possibly new to agentic AI systems in general. It explains not just *what*
AgenticForge is, but *why* it's built the way it is: the alternatives that
were on the table at each decision point, and the reasoning for the option
that was picked. Diagrams use [Mermaid](https://mermaid.js.org/), which
renders automatically on GitHub and in most IDEs (VS Code, JetBrains) — no
external tool needed to view them.

If a term is unfamiliar, check the [Glossary](#glossary) at the end before
searching elsewhere.

---

## 1. What is AgenticForge?

AgenticForge is an open-source **agentic AI orchestration platform** for
enterprises. In plain terms: it's the infrastructure that lets a company
run AI agents (LLM-driven programs that can call tools, query data, and take
multi-step actions) safely, observably, and against whichever model provider
makes sense — without every team re-solving the same problems of tool
integration, tracing, access control, and cost control from scratch.

It is being built incrementally across eight milestones (**M1–M8**), each one
a working, demoable increment rather than a big-bang release.

### Goals

- Let an agent call **tools** (internal APIs, databases, files) through one
  consistent, standard protocol.
- Support **multiple LLM providers** (OpenAI, Anthropic, Azure OpenAI,
  self-hosted Ollama/vLLM) without rewriting agent code to switch providers.
- Make every agent run **observable** — trace every model call and tool call.
- Support **human-in-the-loop (HITL)** approval for sensitive tool calls.
- Enforce **RBAC, audit logging, and PII handling** as first-class concerns,
  not bolted on at the end.
- Run entirely on a **developer laptop** via Docker Compose, and move to a
  managed cloud (Helm/Terraform on AWS/Azure/OKE/GCP) later **without
  rearchitecting**.

### Non-goals (for Phase 1 / M1–M8)

- A hosted multi-tenant SaaS control plane (this is the self-hosted engine
  it would run on).
- A visual, no-code agent builder UI (out of scope — this is the backend).
- Training or fine-tuning models — AgenticForge only *calls* models.

---

## 2. Design Philosophy: The Decisions Behind the Architecture

Every non-trivial system sits on a "spectrum" of design choices — there is
rarely one objectively correct answer, only trade-offs suited to the
problem at hand. This section walks through the major spectrum points a
junior engineer should understand, what AgenticForge chose, and why.

### 2.1 Service granularity: coarse services, not a microservice-per-domain mesh

| Spectrum | Description |
|---|---|
| One end | A single monolithic process doing everything |
| Other end | A microservice per business capability (agents-service, tools-service, models-service, runs-service, …) |
| **Chosen** | **A handful of coarse-grained services**, split by *runtime concern*, not by business entity |

AgenticForge has exactly four Python services:
`orchestrator-api` (HTTP surface), `orchestrator-worker` (agent execution),
`mcp-server` (tool exposure), and `ingestion` (data pipelines) — plus a
shared library (`packages/shared`) so business entities like `Agent`,
`Tool`, and `Run` aren't duplicated or drift across services.

**Why:** a microservice-per-entity split adds network hops and deployment
complexity that a small team doesn't get value from yet. Splitting by
*runtime concern* instead — synchronous request handling vs. long-running
async execution vs. tool exposure — maps directly to how each part actually
needs to scale and fail independently. This can be split further later if a
specific service becomes a bottleneck; the shared schema makes that a
lower-risk move than it would be with per-service databases.

### 2.2 Synchronous API + asynchronous execution

| Spectrum | Description |
|---|---|
| One end | The API handler runs the whole agent loop and blocks until done |
| Other end | Everything is event-driven with no synchronous surface at all |
| **Chosen** | **`orchestrator-api` returns immediately; `orchestrator-worker` executes off a Redis-backed queue** |

An agent run can take anywhere from seconds to minutes, and can *pause
indefinitely* waiting on a human approval (see 2.7). A request/response HTTP
handler is the wrong shape for that. `POST /runs` writes a `Run` row,
enqueues a job (via [`arq`](https://arq-docs.helpmanual.io/), a Redis job
queue), and returns `202 Accepted` with a `run_id` immediately. The worker
picks the job up, and clients poll or stream (`sse-starlette`) for status.

**Why:** decouples "accepting work" from "doing work." The API stays fast
and simple; the worker can be scaled horizontally, retried on failure, and
paused/resumed independently of any HTTP connection's lifetime.

### 2.3 Three kinds of state, three purpose-built stores

A common junior-engineer instinct is "we have a database, everything should
live in it." AgenticForge deliberately splits state across three systems:

| State | Owner | Why not the app DB |
|---|---|---|
| **Business state** (`Run.status`, who requested it, approvals) | AgenticForge's Postgres schema (`runs`, `run_approvals`) | This *is* app data — it belongs here |
| **Execution state** (the agent's step-by-step graph position, message history mid-run) | LangGraph's own Postgres checkpointer tables (`checkpoints`, `checkpoint_writes`) | LangGraph already has a battle-tested, resumable state format — reimplementing it would be redundant and fragile |
| **Observability state** (every LLM call, token, latency, cost, tool span) | Langfuse (its own Postgres + ClickHouse + object storage) | Trace volume is high-cardinality, time-series-shaped data — a different access pattern than transactional business data, and Langfuse already solves querying/visualizing it |

**Why this split, not one database:** each store is optimized for its
access pattern. Cramming detailed execution traces into the same
transactional schema as `Run` rows would make that schema a bottleneck for
something that's fundamentally a logging/analytics workload. All three
happen to live in Postgres locally for operational simplicity (one Postgres
server, three schemas/databases) but are logically — and could be
physically — separate.

### 2.4 Tool integration: an open protocol (MCP), not bespoke function-calling

| Spectrum | Description |
|---|---|
| One end | Hand-write a Python function per tool, wired directly into the agent framework's function-calling API |
| Other end | Adopt a standard protocol for exposing and calling tools, decoupled from any one agent framework or model vendor |
| **Chosen** | **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)**, via `mcp-server` (Streamable HTTP transport) |

Tools are exposed by `mcp-server` and consumed by the LangGraph agent in
`orchestrator-worker` through `langchain-mcp-adapters`. Because MCP is a
standard, the same `mcp-server` could also be pointed at by a different
agent framework, or by an external MCP-compatible client (e.g. an IDE),
without any change to how tools are defined.

**Why:** hand-rolled function-calling schemas tend to get tightly coupled to
one framework's calling convention. MCP externalizes "what tools exist and
how to call them" from "what agent framework is calling them," which
matters a lot in a platform meant to outlive any one framework choice.

### 2.5 Scaling tool coverage: generate tools from OpenAPI specs, don't hand-write each one

| Spectrum | Description |
|---|---|
| One end | An engineer writes a wrapper function for every internal API endpoint an agent should call |
| Other end | Any API with an OpenAPI/Swagger spec is automatically turned into a set of callable MCP tools |
| **Chosen** | **Both, in sequence** — manual tools first (M2, to prove the mechanism), then an OpenAPI-to-MCP adapter (M3, to scale coverage) |

**Why:** most enterprises already have OpenAPI specs for their internal
services. Auto-generating tool definitions (`Tool.input_schema`,
`Tool.tool_key`) from those specs means adding a new tool is a registration
step (`ToolSource` row + spec URL), not a code change. Manual tools remain
available for cases the spec doesn't capture well (custom auth flows,
composite operations).

### 2.6 Multi-model support: a registry + routing rules, not a hardcoded SDK call

| Spectrum | Description |
|---|---|
| One end | Agent code calls `openai.ChatCompletion.create(...)` directly |
| Other end | Every model call goes through a registry that resolves a logical `model_key` to a provider, with rules that can route by agent, tag, or cost |
| **Chosen** | **Registry + routing rules** (`model_providers`, `model_registry`, `model_routing_rules` tables, M5) |

An `Agent` references a `default_model_key`, not a provider SDK call.
`ModelRoutingRule` can override that per-condition (e.g. route
`agent_tag: high_stakes` to a specific, more capable/expensive model).
`langchain-core` + provider-specific packages (`langchain-openai`,
`langchain-anthropic`, `langchain-ollama`) provide the actual client
implementations behind that registry.

**Why:** avoids vendor lock-in and hardcoded model choices scattered through
agent code. Swapping a model, adding a new provider, or changing cost/latency
trade-offs becomes a data change, not a code change.

### 2.7 Human-in-the-loop approval as first-class state

| Spectrum | Description |
|---|---|
| One end | Agents run fully autonomously; risky actions are just... allowed |
| Other end | Every tool call requires human approval (defeats the purpose of automation) |
| **Chosen** | **Per-tool `requires_approval` flag; approval is a modeled, queryable, resumable state (`run_approvals`, `Run.status = paused_hitl`)** |

**Why:** in an enterprise setting, some actions (e.g. "send this email,"
"execute this SQL write") need a human in the loop, but most don't. Making
approval a durable row in Postgres (not an in-memory pause) means a run can
sit paused for hours or days, survive a worker restart, and be resumed from
its LangGraph checkpoint exactly where it left off once approved.

### 2.8 Governance designed into the schema from day one, enforced later

| Spectrum | Description |
|---|---|
| One end | Bolt on RBAC/audit/PII handling at the end, once the "real" features work |
| Other end | Block all feature work until governance is fully built |
| **Chosen** | **Schema-first:** `roles`, `permissions`, `api_keys`, `audit_log`, `pii_findings`, and `Tool.pii_policy` all exist in the M1 schema — but *enforcement* is hardened at M8 |

**Why:** retrofitting audit trails and PII handling onto a schema not
designed for them is painful (migrations touching every table, missing
historical data). Defining the shape early — even before it's enforced —
means M1–M7 features are built against tables that already assume
governance will apply, so M8 is about *turning on enforcement*, not
inventing new tables under time pressure.

### 2.9 Vector search inside the primary database, not a separate vector DB

| Spectrum | Description |
|---|---|
| One end | A dedicated vector database (Pinecone, Weaviate, Qdrant, …) |
| Other end | Vector columns live in the same Postgres instance as everything else, via the `pgvector` extension |
| **Chosen** | **`pgvector`** — the `embeddings` table lives in the same schema as `agents`, `runs`, etc. |

**Why:** at the data volumes this platform starts at, a dedicated vector
database is an extra moving part (extra service, extra ops burden, extra
consistency-between-two-databases problem) for a benefit (specialized ANN
performance at huge scale) the project doesn't need yet. `pgvector` gives
"good enough" similarity search with zero additional infrastructure and
transactional consistency with the rest of the data. This is a decision
that can be revisited later if scale demands it — nothing else in the
architecture depends on vectors living in Postgres specifically.

### 2.10 Deployment: local Docker Compose now, cloud later, same code

| Spectrum | Description |
|---|---|
| One end | Design for Kubernetes/cloud from day one |
| Other end | Build only for a laptop, rewrite for production later |
| **Chosen** | **Docker Compose today; Helm/Terraform layered on top later without application rework** |

Every service is a container with environment-variable configuration and no
compose-specific assumptions baked into application code (no code reaches
into `docker-compose.yml`). That means the same images are what a Helm
chart would deploy later — the change at that point is *how* containers are
scheduled and networked, not what's inside them.

**Why:** local Docker Compose is fast to iterate on and doesn't require
cloud credentials or cluster access for a developer to get productive. Since
the services are already stateless-and-config-driven, moving to Kubernetes
is additive infrastructure work, not an application rewrite.

---

## 3. Technology Stack

| Layer | Technology | Why this, not an alternative |
|---|---|---|
| Language / runtime | Python 3.11, `uv` workspace (monorepo) | One dependency manager and lockfile across all services; `uv` is fast and workspace-aware, so shared code (`packages/shared`) is a normal editable dependency, not a copy-pasted module |
| HTTP API | FastAPI + Uvicorn | Async-native, typed request/response models via Pydantic, automatic OpenAPI docs — which also means `orchestrator-api` itself is a candidate for MCP tool generation later |
| Agent execution | [LangGraph](https://langchain-ai.github.io/langgraph/) | Purpose-built for stateful, resumable, multi-step agent workflows with built-in checkpointing — a better fit than a plain LLM-calling loop once HITL pausing and retries are required |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) (official Python SDK), Streamable HTTP transport | Open standard for tool exposure, decoupled from any one agent framework (see [2.4](#24-tool-integration-an-open-protocol-mcp-not-bespoke-function-calling)) |
| Job queue | Redis 7 + `arq` | Lightweight async Python job queue; avoids pulling in a heavier broker (Celery/RabbitMQ) for a workload that's "run this agent job" rather than complex routing topologies |
| Primary database | PostgreSQL 16 + `pgvector` | One relational store for business data, ingestion metadata, and vector embeddings (see [2.9](#29-vector-search-inside-the-primary-database-not-a-separate-vector-db)) |
| Schema migrations | Alembic | Standard for SQLAlchemy-based schemas; runs as a one-shot `migrate` container before app services start |
| ORM / models | SQLAlchemy 2.0 (async), Pydantic | Typed models shared across services via `packages/shared` |
| LLM provider clients | `langchain-openai`, `langchain-anthropic`, `langchain-ollama` (+ Azure OpenAI, vLLM via OpenAI-compatible endpoints) | Consistent `langchain-core` interface across providers, so the model registry can swap providers without changing call sites |
| Observability / tracing | Langfuse (self-hosted OSS, v3) | Purpose-built for LLM trace/cost/latency observability; self-hosting keeps trace data (which may include PII) inside the same trust boundary |
| File parsing (ingestion) | `unstructured` | Handles heterogeneous document formats (PDF, DOCX, HTML, …) for the RAG ingestion pipeline |
| Text chunking | `langchain-text-splitters` | Standard chunking strategies compatible with the rest of the LangChain/LangGraph stack already in use |
| Semantic / BI layer | [Cube.dev](https://cube.dev/) | Purpose-built semantic layer for defining metrics once and querying them consistently — from SQL, REST, or an agent tool — rather than agents generating ad hoc SQL against raw tables |
| Local orchestration | Docker Compose v2 | See [2.10](#210-deployment-local-docker-compose-now-cloud-later-same-code) |
| Target cloud orchestration | Helm + Terraform (AWS/Azure/OKE/GCP) | Layered on later; not implemented in Phase 1 |
| Lint / type-check / test | `ruff`, `mypy`, `pytest` + `pytest-asyncio` + `testcontainers` | `testcontainers` spins up real Postgres/Redis in tests rather than mocking them — consistent with the project's general preference for real dependencies over mocks in integration tests |

---

## 4. High-Level Design (Target Architecture, post-M8)

This is where all eight milestones converge. Earlier milestones are subsets
of this diagram — see [Section 5](#5-milestone-by-milestone-build-out) for
how it's built up incrementally.

```mermaid
flowchart TB
    subgraph Client["Clients"]
        User["Operator / API client"]
    end

    subgraph API["orchestrator-api (FastAPI)"]
        REST["REST surface:\nruns, agents, tools, models, admin"]
        AuthZ["RBAC middleware\n(M8)"]
    end

    subgraph Worker["orchestrator-worker"]
        LG["LangGraph agent runtime"]
        Router["Model router\n(model_registry + rules)"]
    end

    subgraph MCP["mcp-server"]
        ToolsRuntime["Registered MCP tools"]
        Adapter["OpenAPI-to-MCP adapter"]
    end

    subgraph Ingestion["ingestion service"]
        Parse["Parse (unstructured)"]
        Chunk["Chunk (text-splitters)"]
        Embed["Embed"]
    end

    subgraph Data["Shared PostgreSQL (pgvector)"]
        AppSchema[("App schema:\nagents, tools, runs,\nmodel_registry, rbac,\nembeddings, audit_log")]
        Checkpoints[("LangGraph checkpoints")]
    end

    Queue[["Redis (arq queue)"]]
    Langfuse[["Langfuse\n(trace/cost observability)"]]
    Cube[["Cube.dev semantic layer"]]
    Providers[["Model providers:\nOpenAI / Anthropic /\nAzure OpenAI / Ollama / vLLM"]]
    ExtAPIs[["Internal/external\nREST APIs"]]

    User -->|HTTPS| REST
    REST --> AuthZ
    REST -->|write Run, enqueue job| Queue
    REST -->|read/write| AppSchema
    Queue -->|dequeue job| LG
    LG -->|checkpoint state| Checkpoints
    LG --> Router
    Router -->|resolved model call| Providers
    LG -->|tools/call via MCP| ToolsRuntime
    ToolsRuntime -->|generated from spec| Adapter
    Adapter -->|HTTP call| ExtAPIs
    ToolsRuntime -->|vector search| AppSchema
    LG -->|trace spans| Langfuse
    LG -->|RunApproval pending/resume| AppSchema
    Ingestion -->|source pull| ExtAPIs
    Parse --> Chunk --> Embed -->|store vectors| AppSchema
    Cube -->|query metrics| AppSchema
    ToolsRuntime -->|semantic tool| Cube
```

---

## 5. Milestone-by-Milestone Build-Out

Understanding *how* the system was built up, one working increment at a
time, is often more instructive than only seeing the final diagram above.
Each milestone is runnable and demoable on its own.

```mermaid
flowchart LR
    M1["M1\nSkeleton"] --> M2["M2\nFirst MCP tool"]
    M2 --> M3["M3\nOpenAPI→MCP adapter"]
    M3 --> M4["M4\nLangGraph + Langfuse"]
    M4 --> M5["M5\nModel registry"]
    M5 --> M6["M6\nRAG ingestion"]
    M6 --> M7["M7\nSemantic layer"]
    M7 --> M8["M8\nRBAC/audit/PII"]

    style M1 fill:#4a7,stroke:#333
```

| Milestone | Adds | Status |
|---|---|---|
| **M1 — Skeleton** | Docker Compose stack; Postgres + `pgvector`; Alembic initial schema (all tables, even future-milestone ones); empty `orchestrator-api` (`/healthz`) and `mcp-server` (no tools registered yet) | ✅ Done |
| **M2 — First real tools** | Manually-defined MCP tools across two domains — `get_weather` (`demo/mock_api`) and seven DevOps/code-review tools wrapping `demo/mock_devops_api` (`list_open_pull_requests`, `get_pr_diff`, `post_review_comment`, `get_test_run_status`, `create_branch`, `commit_file_change`, `open_pull_request`) — + `ToolSource`/`Tool` registration rows; API-key auth middleware in front of `mcp-server`; `audit_log` write on every tool call | ✅ Done |
| **M3 — OpenAPI-to-MCP adapter** | `mcp_server/adapters/openapi_adapter.py`: given any OpenAPI spec, auto-generates one MCP tool per operation (dynamically-synthesized function per operation, so FastMCP's normal schema introspection applies unchanged) — scales tool coverage without hand-writing wrappers per endpoint. Registered via `ToolSource(kind="openapi")` rows, read at `mcp-server` boot | ✅ Done |
| **M4 — Agent runtime** | `orchestrator-worker` comes online: a supervisor/tools LangGraph (`graphs/supervisor_graph.py`) executes agents, calling MCP tools over the same M2/M3 path, queued via arq/Redis (`POST /api/v1/runs`, `GET /api/v1/runs/{id}`), `AsyncPostgresSaver` checkpointing, Langfuse `CallbackHandler` tracing. Model provider hardcoded via `M4_MODEL_PROVIDER` at launch — superseded by M5 | ✅ Done |
| **M5 — Model registry** | `model_registry/registry.py`: `model_providers`/`model_registry`/`model_routing_rules` resolved live on every run (no restart, unlike M3's boot-time tools); resolution order is explicit `Run.model_override` > matching `ModelRoutingRule` (by `agent_tag`) > `Agent.default_model_key`. Providers wired for real: Azure OpenAI, and Claude via Azure AI Foundry's Anthropic-compatible endpoint (same `anthropic` provider_type as native Anthropic, just a different `base_url`) | ✅ Done |
| **M6 — RAG ingestion** | `ingestion` service: file/SQL/datalake sources parsed, chunked, embedded into `pgvector`; a retrieval MCP tool for agents to query it | ⬜ Planned |
| **M7 — Semantic layer** | Cube.dev definitions in `semantic-layer/cube`, exposed as a queryable metrics layer — including as an agent tool, so agents query defined metrics instead of writing raw SQL | ⬜ Planned |
| **M8 — Governance hardening** | RBAC enforcement (roles/permissions/API keys), `audit_log` writes on mutating actions, PII detection/masking (`pii_findings`, `Tool.pii_policy`) enforced at runtime | ⬜ Planned |

### M1 today (what's actually running)

```mermaid
flowchart LR
    subgraph Compose["Docker Compose"]
        API["orchestrator-api\n/healthz"]
        MCP["mcp-server\n(empty tools/list)"]
        PG[("Postgres 16\n+ pgvector")]
        Migrate["migrate\n(one-shot Alembic)"]
        LF["Langfuse stack\n(web/worker/db/clickhouse/minio)"]
    end
    Migrate --> PG
    API --> PG
    MCP --> PG
```

### M2 today (what's actually running)

```mermaid
sequenceDiagram
    actor Script as demo/scripts/m2_register_tool_and_call.py
    participant PG as Postgres
    participant MCP as mcp-server
    participant Mock as demo/mock_api (weather)

    Script->>PG: ensure Role + ApiKey (principal=demo-caller)
    Script->>PG: ensure ToolSource(kind=manual) + Tool(get_weather)
    Script->>MCP: initialize (Authorization: Bearer <api_key>)
    MCP->>PG: look up hashed_key -> principal
    Script->>MCP: tools/call get_weather {city}
    MCP->>Mock: GET /weather/{city}
    Mock-->>MCP: mock weather JSON
    MCP->>PG: insert audit_log(action=tool_call, actor=principal)
    MCP-->>Script: tool result
    Script->>PG: assert audit_log row exists
```

`ApiKeyAuthMiddleware` (`mcp_server/governance/auth.py`) is a plain ASGI
wrapper around `mcp.streamable_http_app()` — deliberately not using
Starlette's `add_middleware()` registration, so it doesn't depend on
FastMCP's internal middleware-building order. The resolved principal is
threaded through to the tool implementation via a `contextvars.ContextVar`
rather than a framework-specific request-context object, since the MCP
Python SDK doesn't (yet, as of the version this targets) expose one to tool
functions directly.

The DevOps/code-review domain (`demo/mock_devops_api`,
`mcp_server/tools/devops.py`, `demo/scripts/m2_devops_tools_and_call.py`)
follows the exact same shape as the diagram above — seven tools instead of
one, same auth/audit path — so it isn't re-diagrammed separately. It exists
alongside the weather tool (not replacing it) because it previews a real
DevOpsForge use case (PR review, test status, and now git-write actions)
while weather stays as the minimal reference example. Three tools —
`post_review_comment`, `commit_file_change`, `open_pull_request` — are
registered with `Tool.requires_approval = true` since they're write actions;
this doesn't gate anything yet (HITL enforcement is M8) but demonstrates the
registry already distinguishing read vs. write tools from M2 onward.

**Why `create_branch`, `commit_file_change`, and `open_pull_request` exist
already, even though there's no agent yet to drive them:** an "auto-fix a
failing test and open a PR" workflow splits into two concerns — *deciding*
what fix to make (reading a diff/test failure, reasoning about a patch) and
*executing* the mechanical git actions to get that fix in front of a human
reviewer. The first is an agent decision loop (LangGraph, M4+); the second is
just more deterministic API calls, no different in kind from `get_pr_diff`.
Building the mechanical tools now means M4's agent has something real to
call the moment it exists, instead of M4 also having to invent this API
surface. It also deliberately does **not** shortcut the reasoning half — no
LLM call is hidden inside these tools — because that would bypass Langfuse
tracing, the model registry, and the M8 HITL gate that `commit_file_change`/
`open_pull_request` are already flagged for.

### M3 today (what's actually running)

```mermaid
sequenceDiagram
    actor Reg as m3_register_openapi_sources.py
    actor MCPProc as mcp-server (boot)
    participant PG as Postgres
    actor Demo as m3_openapi_adapter_demo.py
    participant MockAPI as demo/mock_api or mock_devops_api

    Reg->>PG: insert ToolSource(kind=openapi, openapi_url, base_url_override)
    Note over MCPProc: process (re)start required — boot-time, not hot-reload
    MCPProc->>PG: SELECT ToolSource WHERE kind='openapi' AND enabled
    loop each ToolSource
        MCPProc->>MockAPI: GET {openapi_url} (fetch spec)
        MockAPI-->>MCPProc: OpenAPI 3.x JSON
        loop each operation in spec.paths
            MCPProc->>MCPProc: synthesize a real function (exec) matching\nthe operation's path/query/body params
            MCPProc->>MCPProc: mcp.add_tool(fn, name=operationId)
        end
    end
    Demo->>MCPProc: tools/list
    MCPProc-->>Demo: manual (snake_case) + auto-generated (camelCase) tools
    Demo->>MCPProc: tools/call get_weather {city} / getWeatherByCity {city}
    MCPProc->>MockAPI: (both resolve to the same underlying REST call)
    MockAPI-->>MCPProc: identical response
    MCPProc-->>Demo: identical tool results — adapter output verified against
    Demo->>PG: assert audit_log rows exist for generated-tool calls too
```

**Why registration is boot-time instead of live/hot-reload:** a hot-reload
admin endpoint (`POST /tool-sources` triggering immediate registration
without a restart — see [§7.2](#72-turning-an-openapi-spec-into-mcp-tools-m3))
belongs with `orchestrator-api`'s admin surface, which doesn't exist yet
(M1's `orchestrator-api` is still just `/healthz`). Building that now would
mean M3 also builds a chunk of unrelated admin-API scope. Reading
`ToolSource` rows once at `mcp-server` startup gets the actual adapter
mechanism — spec-to-tool codegen — fully working and testable today; the
"apply without a restart" ergonomics layer on top is a clean, independent
addition for whenever the admin API exists.

**Why generated functions are synthesized with `exec` rather than passed a
raw JSON schema:** the alternative — finding and using whatever
lower-level/undocumented API FastMCP might expose for registering a tool
with an explicit schema — is a guess at SDK internals that could silently
break across `mcp` package versions. Building a *real* Python function with
a *real* parameter signature per operation means FastMCP's completely normal,
documented, type-hint-based introspection (the same path `@mcp.tool()` uses
for hand-written tools) does the schema derivation — no reliance on
internals specific to this adapter.

### M4 today (what's actually running)

```mermaid
sequenceDiagram
    actor Demo as m4_langgraph_agent_demo.py
    participant API as orchestrator-api
    participant PG as Postgres
    participant Q as Redis (arq)
    participant W as orchestrator-worker
    participant MCP as mcp-server
    participant LLM as Model provider (M4_MODEL_PROVIDER)
    participant LF as Langfuse

    Demo->>PG: ensure Agent(name=weather-devops-agent, graph_key=supervisor_graph)
    Demo->>API: POST /api/v1/runs {agent_name, input: {message}}
    API->>PG: insert Run(status=queued)
    API->>Q: enqueue_job("run_graph", run_id)
    API-->>Demo: {run_id}

    Q->>W: dequeue run_graph(run_id)
    W->>PG: Run.status = running
    W->>W: mint/reuse orchestrator-worker API key (rbac.bootstrap)
    W->>MCP: fetch tools (langchain-mcp-adapters, Bearer auth)
    W->>W: build supervisor_graph, AsyncPostgresSaver(thread_id=run_id)
    W->>LLM: agent node: chat completion
    LLM-->>W: tool call requested (e.g. get_weather)
    W->>MCP: tools/call get_weather
    MCP-->>W: tool result
    W->>LF: trace spans (LLM generation + tool call), trace_id=run_id
    W->>LLM: agent node: continue with tool result
    LLM-->>W: final answer
    W->>PG: Run.status=completed, output, langfuse_trace_id=run_id

    loop poll
        Demo->>API: GET /api/v1/runs/{run_id}
        API->>PG: select Run
        API-->>Demo: status/output
    end
    Demo->>Demo: print Langfuse trace link (host/trace/run_id)
```

**Why `Run.langfuse_trace_id` is just set to `run_id` rather than a
separately-generated Langfuse ID:** `get_langfuse_callback_handler(trace_id=run_id)`
forces Langfuse to use our own ID for the trace, so the two systems'
identifiers for "this run" are the same string — no join table, no
round-trip to Langfuse to discover its generated ID before storing it.

**Why the worker mints its own API key via the same `rbac.bootstrap` helper
the demo scripts use, rather than a hardcoded/shared secret:** the worker is
just another MCP client from `mcp-server`'s point of view — reusing the
exact same principal/role/audit path means a tool call made by an agent
shows up in `audit_log` with `actor='orchestrator-worker'`, distinguishable
from a human-triggered demo-script call, for free. Real secret provisioning
(rotation, a proper secrets manager instead of a `.run/*.txt` file) is M8
scope; this is the pragmatic bootstrap until then.

**Why the graph is looked up via a small `_GRAPH_BUILDERS` dict keyed by
`Agent.graph_key`, instead of just always calling `build_graph()`:** M4 only
has one graph, so this looks like unnecessary indirection today — but
`graph_key` already exists on `Agent` (from the M1 schema-first design, see
§2.8), and routing through it now means adding a second graph type later is
a dict entry, not a change to `tasks.py`'s control flow.

### M5 today (what's actually running)

```mermaid
sequenceDiagram
    actor Demo as m5_multi_model_routing_demo.py
    participant API as orchestrator-api
    participant PG as Postgres
    participant W as orchestrator-worker
    participant Registry as model_registry/registry.py
    participant Azure as Azure OpenAI
    participant Claude as Claude (Azure AI Foundry)

    Note over PG: m5_register_model_providers.py already ran:<br/>2 ModelProviders, 2 ModelRegistryEntrys,<br/>1 ModelRoutingRule(agent_tag=cost_sensitive),<br/>Agent retagged cost_sensitive

    Demo->>API: POST /api/v1/runs {agent_name, input} (no override)
    API->>PG: insert Run(model_override=NULL)
    Note over W: dequeued via arq, same path as M4
    W->>Registry: resolve_model_key(agent, model_override=None)
    Registry->>PG: select ModelRoutingRule order by priority desc
    Registry->>Registry: agent.config.tags has "cost_sensitive" -> rule matches
    Registry-->>W: "claude-haiku-4-5"
    W->>Registry: get_chat_model("claude-haiku-4-5")
    Registry->>PG: join model_registry + model_providers
    Registry-->>W: ChatAnthropic(base_url=Foundry endpoint, ...)
    W->>Claude: chat completion
    Claude-->>W: response
    W->>PG: Run.output.model_key = "claude-haiku-4-5"

    Demo->>API: POST /api/v1/runs {agent_name, input, model_override: "azure-gpt-5.2-chat"}
    API->>PG: insert Run(model_override="azure-gpt-5.2-chat")
    W->>Registry: resolve_model_key(agent, model_override="azure-gpt-5.2-chat")
    Registry-->>W: "azure-gpt-5.2-chat" (override short-circuits, rule never checked)
    W->>Registry: get_chat_model("azure-gpt-5.2-chat")
    Registry-->>W: AzureChatOpenAI(azure_endpoint=..., azure_deployment=...)
    W->>Azure: chat completion
    Azure-->>W: response
    W->>PG: Run.output.model_key = "azure-gpt-5.2-chat"

    Demo->>Demo: assert the two runs used different, expected model_keys
```

**Why resolution queries Postgres fresh on every call instead of caching
the registry in-process:** unlike M3's OpenAPI tools (which must be
compiled into real Python functions with real signatures — inherently a
one-time, boot-time cost), a model/provider/rule lookup is just a row
lookup with no code generation involved. Caching would save a query but
introduce a staleness window where a newly-registered provider doesn't take
effect until a restart — exactly the ergonomics problem M3 accepted as a
tradeoff and explicitly flagged as a future improvement. M5 has no reason to
accept that same tradeoff when the lookup itself is cheap.

**Why Claude-via-Azure-AI-Foundry doesn't get its own `provider_type`:**
Azure AI Foundry's Anthropic-compatible endpoint speaks the same protocol
`langchain-anthropic`'s `ChatAnthropic` already targets — the only
difference from native Anthropic is passing a custom `base_url`. Treating
it as a separate `provider_type` (e.g. `"azure_foundry_anthropic"`) would
duplicate the `"anthropic"` branch in `build_chat_model()` for zero
behavioral difference. Any Anthropic-protocol-compatible endpoint is just
`provider_type="anthropic"` with `base_url` set or unset.

**Why `auth_secret_ref` stores an env var *name*, not the secret:** matches
the schema's original intent ("secret refs, never raw secrets") without
needing a real secrets manager yet — that's explicitly deferred to M8. The
registry does `os.environ[provider.auth_secret_ref]`, so the DB never holds
a credential, only a pointer to where one lives.

---

## 6. Data Model

The schema is defined once in `packages/shared`, migrated by Alembic, and
shared read/write by `orchestrator-api`, `orchestrator-worker`, and
`ingestion`. It's grouped here by domain, matching the milestones that
populate/enforce each group.

### 6.1 Agents & Tools (M1–M3)

```mermaid
erDiagram
    AGENT ||--o{ AGENT_TOOL : has
    TOOL ||--o{ AGENT_TOOL : "used by"
    TOOL_SOURCE ||--o{ TOOL : exposes
    TOOL_SOURCE ||--o{ TOOL_CREDENTIAL : authenticates

    AGENT {
        uuid id
        string name
        string graph_key
        string default_model_key
        jsonb config
    }
    TOOL_SOURCE {
        uuid id
        string kind "openapi | manual | sql_semantic | rag | code_exec"
        string openapi_url
        jsonb auth_config
    }
    TOOL {
        uuid id
        string tool_key
        jsonb input_schema
        bool requires_approval
        string pii_policy "mask | block | allow"
    }
    TOOL_CREDENTIAL {
        uuid id
        string secret_ref
        datetime rotated_at
    }
```

### 6.2 Model Registry (M5)

```mermaid
erDiagram
    MODEL_PROVIDER ||--o{ MODEL_REGISTRY_ENTRY : offers

    MODEL_PROVIDER {
        uuid id
        string provider_type "openai | anthropic | azure_openai | ollama | vllm"
        string base_url
        string auth_secret_ref "env var name, not the secret itself"
        jsonb config "provider-specific extras, e.g. api_version"
    }
    MODEL_REGISTRY_ENTRY {
        uuid id
        string model_key
        string model_type "chat | embedding"
        int context_window
        numeric cost_per_1k_input
        bool is_default
    }
    MODEL_ROUTING_RULE {
        uuid id
        jsonb match_condition
        string target_model_key
        int priority
    }
```

### 6.3 Runs & Human-in-the-Loop (M4)

```mermaid
erDiagram
    AGENT ||--o{ RUN : executes
    RUN ||--o{ RUN_APPROVAL : gates

    RUN {
        uuid id "also LangGraph thread_id"
        string status "queued | running | paused_hitl | completed | failed"
        jsonb input
        jsonb output
        string model_override "caller-supplied model_key, M5; null = registry-resolved"
        string langfuse_trace_id
    }
    RUN_APPROVAL {
        uuid id
        string tool_call_id
        string status "pending | approved | rejected"
        string decided_by
    }
```

### 6.4 Ingestion & RAG (M6)

```mermaid
erDiagram
    INGESTION_SOURCE ||--o{ INGESTION_RUN : produces
    INGESTION_SOURCE ||--o{ EMBEDDING : yields

    INGESTION_SOURCE {
        uuid id
        string kind "file | sql_db | datalake"
        jsonb connection_config
        string embedding_model_key
    }
    INGESTION_RUN {
        uuid id
        string status
        int rows_processed
        int chunks_created
    }
    EMBEDDING {
        uuid id
        string document_id
        text chunk_text
        vector embedding "1024-dim"
    }
```

### 6.5 RBAC & Governance (M8)

```mermaid
erDiagram
    ROLE ||--o{ ROLE_PERMISSION : grants
    PERMISSION ||--o{ ROLE_PERMISSION : "granted via"
    ROLE ||--o{ API_KEY : assigned

    ROLE {
        uuid id
        string name "admin | operator | agent_caller"
    }
    PERMISSION {
        uuid id
        string name "e.g. runs:create"
    }
    API_KEY {
        uuid id
        string hashed_key
        string principal_name
        datetime revoked_at
    }
    AUDIT_LOG {
        uuid id
        string actor
        string action
        jsonb before
        jsonb after
    }
    PII_FINDING {
        uuid id
        string entity_type "e.g. EMAIL_ADDRESS"
        string action_taken "masked | blocked"
    }
```

---

## 7. Key Runtime Flows

### 7.1 Agent run lifecycle (with HITL pause), from M4 onward

This is the **target flow including the HITL pause/resume branch**, which is
M8 scope (`RunApproval`, `interrupt()`) — not implemented yet. What's
actually running today (M4: the non-HITL path only, real endpoint is
`POST /api/v1/runs` not `POST /runs`) is diagrammed in
[§5, "M4 today"](#m4-today-whats-actually-running). Everything above the
`alt tool requires_approval` branch below matches reality already.

```mermaid
sequenceDiagram
    actor Client
    participant API as orchestrator-api
    participant PG as Postgres
    participant Q as Redis (arq)
    participant W as orchestrator-worker (LangGraph)
    participant MCP as mcp-server
    participant LLM as Model provider
    participant LF as Langfuse

    Client->>API: POST /runs {agent, input}
    API->>PG: insert Run(status=queued)
    API->>Q: enqueue run job
    API-->>Client: 202 Accepted {run_id}

    Q->>W: dequeue job
    W->>PG: load/create checkpoint (thread_id = run_id)
    W->>LLM: chat completion (via model router)
    LLM-->>W: response requesting a tool call
    W->>MCP: tools/call
    MCP-->>W: tool result
    W->>LF: emit trace spans (model + tool calls)

    alt tool requires_approval = true
        W->>PG: insert RunApproval(pending)
        W->>PG: Run.status = paused_hitl
        Note over Client,PG: worker exits, run stays parked on its checkpoint
        Client->>API: POST /runs/{id}/approvals/{id}/approve
        API->>PG: RunApproval.status = approved
        API->>Q: enqueue resume job
        Q->>W: dequeue resume job
        W->>PG: resume from checkpoint
    end

    W->>LLM: continue reasoning
    LLM-->>W: final answer
    W->>PG: Run.status = completed, output = ...
    W->>LF: close trace
```

### 7.2 Turning an OpenAPI spec into MCP tools (M3)

This is the **target flow**, once `orchestrator-api` has an admin surface
(not yet built — M1's `orchestrator-api` is still just `/healthz`) and M4's
LangGraph agent exists as the caller. What's actually running today —
demo scripts insert the `ToolSource` row directly, `mcp-server` reads it at
boot rather than being triggered by an API call, and no per-operation `Tool`
row is inserted (the running tool registry inside `mcp-server` is the source
of truth for generated tools; only `ToolSource` is persisted) — is
diagrammed in [§5, "M3 today"](#m3-today-whats-actually-running). The
underlying adapter mechanism (spec → generated tool functions) is identical
in both; what differs is only *what triggers* registration and *whether* a
`Tool` row is written per generated operation.

```mermaid
sequenceDiagram
    actor Admin
    participant API as orchestrator-api
    participant PG as Postgres
    participant Adapter as OpenAPI-to-MCP adapter
    participant MCP as mcp-server
    actor Agent as LangGraph agent

    Admin->>API: POST /tool-sources {kind: openapi, openapi_url}
    API->>PG: insert ToolSource
    API->>Adapter: trigger generation
    Adapter->>Adapter: fetch + parse OpenAPI spec
    loop each operation in spec
        Adapter->>PG: insert Tool (tool_key, input_schema)
    end
    Adapter->>MCP: register dynamic tool handlers

    Agent->>MCP: tools/list
    MCP-->>Agent: tool definitions (manual + generated)
    Agent->>MCP: tools/call {tool_key, args}
    MCP->>MCP: look up ToolCredential, build HTTP request
    MCP->>MCP: call target REST API
    MCP-->>Agent: tool result
```

### 7.3 RAG ingestion and retrieval (M6)

```mermaid
sequenceDiagram
    actor Admin
    participant Ing as ingestion service
    participant Src as Source (file/SQL/datalake)
    participant PG as Postgres (pgvector)
    participant MCP as mcp-server (RAG tool)
    actor Agent as LangGraph agent

    Admin->>Ing: register IngestionSource
    Ing->>PG: insert IngestionRun(status=running)
    Ing->>Src: pull documents
    Ing->>Ing: parse (unstructured)
    Ing->>Ing: chunk (text-splitters)
    Ing->>Ing: embed chunks (via model registry)
    Ing->>PG: insert Embedding rows (vector column)
    Ing->>PG: IngestionRun(status=completed, chunks_created=N)

    Note over Agent,PG: later, during a run
    Agent->>MCP: tools/call {rag_search, query}
    MCP->>PG: vector similarity search (pgvector)
    PG-->>MCP: top-k chunks
    MCP-->>Agent: retrieved context
```

---

## 8. Deployment Topology

### 8.1 Today: local Docker Compose

```mermaid
flowchart TB
    subgraph Host["Developer laptop"]
        subgraph AppStack["docker-compose.yml"]
            PG[("postgres\n+pgvector :5432")]
            Redis[("redis :6379")]
            Migrate["migrate\n(one-shot)"]
            API["orchestrator-api :8000"]
            MCP["mcp-server :8100"]
        end
        subgraph LFStack["docker-compose.langfuse.yml"]
            LFWeb["langfuse-web :3000"]
            LFWorker["langfuse-worker"]
            LFdb[("langfuse-db :5433")]
            CH[("clickhouse :8123")]
            Minio[("minio :9090")]
        end
    end
    Migrate --> PG
    API --> PG
    API --> Redis
    MCP --> PG
    LFWorker --> LFdb
    LFWorker --> CH
    LFWorker --> Minio
    LFWeb --> LFWorker
```

Brought up together with one command (`make up`), which composes both files
so the app stack and the Langfuse stack run side by side without port or
volume collisions (separate Postgres instances, separate port ranges).

### 8.2 Later: target cloud topology (not yet implemented)

```mermaid
flowchart TB
    subgraph K8s["Kubernetes cluster (Helm)"]
        APIpods["orchestrator-api\n(N replicas)"]
        Workerpods["orchestrator-worker\n(N replicas, autoscaled\non queue depth)"]
        MCPpods["mcp-server\n(N replicas)"]
    end
    ManagedPG[("Managed Postgres\n(RDS / Cloud SQL / Azure DB)\n+ pgvector")]
    ManagedRedis[("Managed Redis\n(ElastiCache / Memorystore)")]
    LangfuseHosted["Langfuse\n(self-hosted in-cluster\nor Langfuse Cloud)"]
    Secrets["Secrets manager\n(replaces ToolCredential\nsecret_ref target)"]

    APIpods --> ManagedPG
    APIpods --> ManagedRedis
    Workerpods --> ManagedPG
    Workerpods --> ManagedRedis
    Workerpods --> LangfuseHosted
    MCPpods --> ManagedPG
    MCPpods --> Secrets
```

**Why this transition is low-risk:** application code already reads all
connection info from environment variables (`DATABASE_URL`,
`MCP_SERVER_PORT`, etc.) — see [2.10](#210-deployment-local-docker-compose-now-cloud-later-same-code).
Moving from Compose to Helm changes *how* those env vars are supplied and
*how* containers are scheduled, not the containers themselves.

---

## 9. Security & Governance Model (M8)

```mermaid
flowchart LR
    Req["Incoming request\n(API key)"] --> Authn["Authenticate\n(api_keys.hashed_key)"]
    Authn --> Authz["Authorize\n(role → permissions)"]
    Authz -->|denied| Deny["403"]
    Authz -->|allowed| Action["Perform action\n(e.g. create Run,\nregister Tool)"]
    Action --> Audit["Write audit_log\n(before/after)"]
    Action --> ToolCall["Tool call executes"]
    ToolCall --> PIIScan["PII scan\n(per Tool.pii_policy)"]
    PIIScan -->|mask| Masked["Redact + log\npii_findings(masked)"]
    PIIScan -->|block| Blocked["Reject + log\npii_findings(blocked)"]
    PIIScan -->|allow| Pass["Pass through"]
```

Even though enforcement lands at M8, every table this flow depends on
(`api_keys`, `roles`, `permissions`, `role_permissions`, `audit_log`,
`pii_findings`, `Tool.pii_policy`) exists from M1 — see
[2.8](#28-governance-designed-into-the-schema-from-day-one-enforced-later).

---

## Glossary

| Term | Meaning |
|---|---|
| **Agent** | An LLM-driven program that can reason over multiple steps and call tools, defined by a `graph_key` (which LangGraph graph to run) and a default model |
| **MCP (Model Context Protocol)** | An open standard for exposing "tools" (callable actions) to LLM-driven clients over a consistent transport, independent of any one model or agent framework |
| **LangGraph** | A framework for building agents as state machines ("graphs") with built-in support for pausing, resuming, and checkpointing execution state |
| **Checkpointer** | The mechanism LangGraph uses to persist an agent's mid-execution state so a run can be paused (e.g. for HITL approval) and resumed later from exactly where it left off |
| **HITL (Human-in-the-loop)** | A workflow pattern where certain agent actions require explicit human approval before proceeding |
| **RAG (Retrieval-Augmented Generation)** | Improving an LLM's answers by first retrieving relevant chunks of text (via vector similarity search) and including them in the prompt |
| **pgvector** | A PostgreSQL extension adding a vector column type and similarity-search operators, used here for RAG retrieval |
| **Langfuse** | An open-source LLM observability platform — traces model calls, tool calls, latency, token usage, and cost |
| **Cube.dev** | A semantic layer tool: define business metrics once (e.g. "monthly active users"), query them consistently from SQL, REST, or an agent tool |
| **arq** | A lightweight async job queue for Python, backed by Redis — used to run agent jobs off the request/response cycle |
| **RBAC (Role-Based Access Control)** | Restricting actions based on the role assigned to the calling principal (API key), rather than per-user special-casing |
| **Model registry** | The `model_providers`/`model_registry`/`model_routing_rules` tables that let AgenticForge resolve a logical model name to an actual provider/model at call time |
