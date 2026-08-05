# Local Install Guide (Ubuntu / Linux)

Step-by-step setup for running AgenticForge Phase 1 (Agentic Orchestrator + MCP
Server) on your machine. Written for a native Ubuntu terminal.

Two paths, pick one:

- **[Path A — Docker Compose](#path-a-docker-compose)**: brings up Postgres,
  Redis, and a self-hosted Langfuse stack alongside the app services. Closest
  to how this will eventually deploy (Helm/K8s later); more moving parts now.
- **[Path B — Native (no Docker)](#path-b-native-no-docker)**: run the two
  Python services directly in a venv against **an existing Postgres you
  already have** (e.g. from another WSL project). M1 doesn't touch Redis or
  Langfuse yet — those only get wired into the code at M4 — so this path is
  genuinely simpler if you already have Postgres running and don't want
  Docker in the loop yet.

---

## Path A: Docker Compose

## 1. Prerequisites

1. **Update your package index**
   ```bash
   sudo apt-get update
   ```

2. **Docker Engine + Docker Compose v2** — install via Docker's official apt
   repository (more reliable than the one-line convenience script, which can
   fail silently if `curl` isn't installed or the download is blocked):
     ```bash
     # Add Docker's official GPG key
     sudo apt-get update
     sudo apt-get install -y ca-certificates curl
     sudo install -m 0755 -d /etc/apt/keyrings
     sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
     sudo chmod a+r /etc/apt/keyrings/docker.asc

     # Add the repository to Apt sources
     echo \
       "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
       $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
       sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
     sudo apt-get update

     # Install Docker Engine, CLI, and the Compose v2 plugin
     sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
     ```
   - Full reference: https://docs.docker.com/engine/install/ubuntu/
   - Let your user run `docker` without `sudo`:
     ```bash
     sudo usermod -aG docker $USER
     newgrp docker
     ```
   - Verify:
     ```bash
     docker --version
     docker compose version
     ```
   - **If the one-line convenience script (`curl -fsSL https://get.docker.com | sh`) is what you tried and hit "no such file or directory"**: that means the `curl -o get-docker.sh` step never actually wrote the file, almost always because either `curl` isn't installed (`sudo apt-get install -y curl` and retry) or the download was blocked/failed silently — run the `curl` line on its own first and check for an error before piping into `sh`. The apt-repository method above avoids this failure mode entirely and is the recommended path.

3. **`uv`** (Python package/workspace manager, only needed for local non-container dev — `make up` alone doesn't require it):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   exec $SHELL   # reload PATH
   uv --version
   ```

4. **`make`**: `sudo apt-get install -y make`

5. **`git`** (if not already present): `sudo apt-get install -y git`

## 2. Get the code

```bash
cd ~
git clone <your-remote-url> AgenticForge
cd AgenticForge
```

If you're instead working from a copy already on disk, just `cd` into it.

## 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in what you plan to use now — everything else can stay
blank until the milestone that needs it:

| Variable | Needed for | Notes |
|---|---|---|
| `DATABASE_URL` | Everything | Default value already matches the Compose Postgres — leave as-is for local dev |
| `MCP_SERVER_PORT` | M1+ | Default `8100`, only change if that port is taken |
| `M4_MODEL_PROVIDER` | M4 (agent runtime) | `openai` \| `azure_openai` \| `anthropic` \| `ollama` — which provider the M4 agent hardcodes; full multi-provider routing is M5 |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `AZURE_OPENAI_*` | M4 (whichever you picked above), generalized at M5 | Fill in credentials for your chosen `M4_MODEL_PROVIDER`; leave the rest blank |
| `OLLAMA_BASE_URL` / `VLLM_BASE_URL` | M4/M5, local/open models | Only if you're running Ollama/vLLM locally |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | M4 (tracing) | You generate these in step 6 below, *after* Langfuse is up — leave blank for now |

## 4. Bring up the stack

Run these commands from the repository root. If Docker Desktop is managing Docker on your machine, make sure the engine is running before you start.

```bash
make up
```

This builds the images and starts, in order: `postgres` (with `pgvector`),
`redis`, the one-shot `migrate` job (runs Alembic against Postgres), then
`orchestrator-api` and `mcp-server` — plus the self-hosted Langfuse stack
(`langfuse-web`, `langfuse-worker`, its own Postgres/ClickHouse/MinIO/Redis).

Check everything came up healthy:

```bash
make ps
```

All containers should show `running`/`healthy`. If `migrate` shows
`exited (0)`, that's expected — it's a one-shot job, not a long-running
service.

## 5. Verify the core services

```bash
make demo-m1
```

Expected output:
```
orchestrator-api OK
langfuse OK
```

Manual checks if you want more detail:

```bash
curl http://localhost:8000/healthz        # orchestrator-api
curl http://localhost:3000/api/public/health   # Langfuse
```

Confirm `pgvector` is actually enabled and the schema migrated:

```bash
docker compose -f infra/docker-compose/docker-compose.yml exec postgres \
  psql -U agenticforge -d agenticforge -c "\dx" -c "\dt"
```

You should see `vector` in the extensions list and all the tables from
`packages/shared/src/agenticforge_shared/db/models.py` (`agents`, `tools`,
`model_registry`, `runs`, `embeddings`, `audit_log`, etc.).

## 6. Set up Langfuse (one-time)

1. Open http://localhost:3000
2. Create your first user account, organization, and project through the UI
3. In the project settings, generate an API key pair
4. Copy the public/secret keys into `.env` as `LANGFUSE_PUBLIC_KEY` /
   `LANGFUSE_SECRET_KEY` — these aren't used until M4 wires tracing into
   LangGraph, but it's easiest to grab them now while you're in the UI

## 7. Check the MCP server directly (optional but useful)

The MCP server has no tools registered yet in M1 — this just confirms it's
reachable and speaking MCP correctly:

```bash
npx @modelcontextprotocol/inspector http://localhost:8100
```

This opens a browser-based inspector; `tools/list` should return an empty
list at this stage. If `npx` is not available, install Node.js/npm first (for
example, `sudo apt-get install -y nodejs npm`) and retry.

Notes:
- In **M1**, `tools/list` being empty is expected.
- In **M2**, `tools/list` should show **8 tools** (weather + DevOps).
- If you're running the mock APIs from **WSL** but running `mcp-server` inside
  **Docker**, Docker networking can prevent the MCP server from reaching the
  mock APIs. The simplest working setup for M2 demos is: keep Docker up for
  Postgres/Langfuse, but run `mcp-server` natively in WSL (see C1 below).

## 8. Tear down / reset

```bash
make down                     # stop and remove containers
docker volume rm agenticforge_postgres_data langfuse_postgres_data \
  langfuse_clickhouse_data langfuse_minio_data   # wipe all data for a clean slate
```

---

## Path B: Native (no Docker)

Runs `orchestrator-api` and `mcp-server` directly in a Python venv against a
Postgres instance you already have. No Redis, no Langfuse — both are only
needed starting at M4, so they're simply not part of this path yet.

### B1. Prerequisites
0. Open WSL Ubuntu and change into your repository directory. If you cloned the repo into a Windows path, the equivalent command is typically `cd /mnt/c/projects/AgenticForge`.
1. **`uv`**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   exec $SHELL
   uv --version
   ```
2. **`make`** and **`git`**, if not already present: `sudo apt-get install -y make git`
3. Your existing Postgres, reachable from this shell (`psql -h <host> -U <user> -d postgres -c '\q'` should connect without error).

### B2. Get the code

```bash
cd ~
git clone <your-remote-url> AgenticForge   # or cd into your existing copy
cd AgenticForge
```

### B3. Enable `pgvector` on your existing Postgres

`pgvector` is a Postgres *extension*, not a separate service, so it installs
into the Postgres server you already have — it just needs the extension
package matching your installed Postgres major version.

1. Check your Postgres version:
   ```bash
   psql -h <host> -U <user> -d postgres -c 'SHOW server_version;'
   ```
2. Install the matching extension package (adjust `16` to your version):
   ```bash
   sudo apt-get install -y postgresql-16-pgvector
   ```
   If apt doesn't have a package for your version, build from source instead:
   https://github.com/pgvector/pgvector#installation
3. Create a database for AgenticForge (skip if you'd rather reuse an existing one — just adjust the connection string below accordingly) and enable the extension in it:
   ```bash
   psql -h <host> -U <user> -d postgres -c "CREATE DATABASE agenticforge;"
   psql -h <host> -U <user> -d agenticforge -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

### B4. Configure environment variables

```bash
cp .env.example .env
```

Edit `DATABASE_URL` in `.env` to point at your existing Postgres instead of
the Docker Compose default, e.g.:
```
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/agenticforge
```
Leave `LANGFUSE_*` and the model provider keys blank for now — nothing in M1
reads them.

### B5. Install dependencies and migrate

```bash
make sync            # uv sync --all-packages --group dev — installs everything into .venv/
make migrate-native  # runs Alembic against DATABASE_URL from .env
```

Confirm the schema landed:
```bash
psql -h <host> -U <user> -d agenticforge -c "\dx" -c "\dt"
```
You should see `vector` in the extensions list and all the tables from
`packages/shared/src/agenticforge_shared/db/models.py`.

### B6. Run the services

```bash
make run-native    # starts orchestrator-api (:8000) and mcp-server (:8100) in the background
make demo-native   # curls orchestrator-api /healthz
make logs-native   # tail both service logs
make stop-native   # stop both
```

Or run them in the foreground in two separate terminals instead (useful while
actively developing, since you see output/errors immediately):
```bash
uv run uvicorn orchestrator_api.main:app --host 0.0.0.0 --port 8000
uv run python -m mcp_server.server
```

### B7. Continue with the common steps

Once the service stack is up through either Path A or Path B, continue with the
common steps below for M2 verification, local dev workflow, and later milestones.

## Common steps

These steps are useful whether you followed Path A or Path B.

### C1. Test M2 — how to know it's working

M2 adds: API-key auth on `mcp-server`, audit logging on every tool call, and
8 manually-registered tools across two domains (`get_weather`, plus 7
DevOps/code-review tools). This section is the definitive "did M2 install
correctly" check.

**Step 1 — run both automated demos:**

```bash
make demo-m2           # weather: demo/mock_api + get_weather
make demo-m2-devops    # DevOps/code-review: demo/mock_devops_api + 7 tools
```

If you're using **Docker Compose for Postgres/Langfuse** but running the demos
from **WSL**, stop the Docker MCP server and run it natively so it can reach
the mock APIs:

```bash
docker compose -f infra/docker-compose/docker-compose.yml stop mcp-server
uv run python -m mcp_server.server
```

`demo-m2` runs `demo/scripts/m2_register_tool_and_call.py`: creates/reuses an
API key for a `demo-caller` principal (stored at `.run/m2_demo_api_key.txt`
so re-runs don't pile up new keys), registers `ToolSource`/`Tool` bookkeeping
rows, calls `get_weather` as an authenticated MCP client, and asserts a
matching `audit_log` row was written.

`demo-m2-devops` runs `demo/scripts/m2_devops_tools_and_call.py` against the
same key/principal: registers and calls all 7 DevOps tools
(`list_open_pull_requests`, `get_pr_diff`, `post_review_comment`,
`get_test_run_status`, `create_branch`, `commit_file_change`,
`open_pull_request`), asserting an `audit_log` row for each. The three write
tools (`post_review_comment`, `commit_file_change`, `open_pull_request`) are
registered `requires_approval=True` — previewing the M8 HITL gate, not yet
enforced.

**✅ M2 is working if both commands exit cleanly (no Python traceback / no
`AssertionError`) and end with output like this:**

```
# demo-m2
tools/list -> ['get_weather', 'list_open_pull_requests', 'get_pr_diff', 'post_review_comment', 'get_test_run_status', 'create_branch', 'commit_file_change', 'open_pull_request']
tools/call get_weather(london) -> [...]
audit_log confirmed: actor='demo-caller' action='tool_call' after={...}

# demo-m2-devops (7 lines, one per tool)
audit_log confirmed for list_open_pull_requests: actor='demo-caller'
audit_log confirmed for get_pr_diff: actor='demo-caller'
audit_log confirmed for post_review_comment: actor='demo-caller'
audit_log confirmed for get_test_run_status: actor='demo-caller'
audit_log confirmed for create_branch: actor='demo-caller'
audit_log confirmed for commit_file_change: actor='demo-caller'
audit_log confirmed for open_pull_request: actor='demo-caller'
```

**❌ M2 is *not* working if you see:** an `AssertionError` on the audit_log
check, a connection-refused error (services aren't running — go back to
Path A/B setup), or a 401/unauthorized error from the MCP client (see
Troubleshooting).

Note: the mock DevOps API keeps branches/commits/PRs in memory only (no
persistence), so re-running `make demo-m2-devops` **without** restarting
`demo/mock_devops_api` first will 409 on `create_branch` (the branch from
the previous run still exists in that process's memory) — that's expected,
not a failure; restart with `make stop-native && make demo-m2-devops`.

**Step 2 (optional) — confirm auth is actually enforced, not just present:**

```bash
curl -i http://localhost:8100/mcp
```
Expect `HTTP/1.1 401 Unauthorized` with no `Authorization` header sent. If
this instead connects/hangs waiting on the MCP protocol handshake, the
`ApiKeyAuthMiddleware` isn't being applied.

**Step 3 (optional) — confirm the registry and audit rows directly in Postgres:**

```bash
psql -h <host> -U <user> -d agenticforge -c \
  "SELECT tool_key, requires_approval, pii_policy FROM tools ORDER BY tool_key;"
psql -h <host> -U <user> -d agenticforge -c \
  "SELECT actor, action, resource_id, created_at FROM audit_log ORDER BY created_at DESC LIMIT 10;"
```
Expect 8 rows in `tools` (matching the `tools/list` output above), and at
least 8 rows in `audit_log` with `resource_id` matching each tool call made.

**Step 4 (optional) — check the MCP server directly with the Inspector:**

```bash
npx @modelcontextprotocol/inspector http://localhost:8100
```
Paste `cat .run/m2_demo_api_key.txt` into the Inspector's Authorization
header field as `Bearer <key>` — without it, every call gets rejected per
Step 2 above.

### C2. Test M3 — OpenAPI-to-MCP adapter

M3 adds a second way to get tools into `mcp-server`: point a `ToolSource` at
an API's OpenAPI spec (`/openapi.json`) and get one MCP tool per operation
auto-generated, no hand-written wrapper needed. It runs alongside M2's manual
tools, not instead of them.

```bash
make demo-m3
```

This one command does three things in sequence (matching the fact that
registration is boot-time, not hot-reload — see
`mcp_server/adapters/openapi_adapter.py` for why):
1. Runs `demo/scripts/m3_register_openapi_sources.py` — inserts two
   `ToolSource(kind="openapi")` rows pointing at the demo weather and DevOps
   APIs' `/openapi.json`.
2. Restarts `mcp-server` (`make restart-mcp-native`) so it picks the new
   `ToolSource` rows up at boot and auto-generates a tool per operation.
3. Runs `demo/scripts/m3_openapi_adapter_demo.py`, which verifies the
   generated tools work.

**✅ M3 is working if `demo-m3` exits cleanly and ends with output like:**

```
tools/list -> ['commitFileChange', 'commit_file_change', 'createBranch', 'create_branch', 'getPullRequestDiff', 'getTestRunStatus', 'getWeatherByCity', 'get_pr_diff', 'get_test_run_status', 'get_weather', 'listOpenPullRequests', 'list_open_pull_requests', 'openPullRequest', 'open_pull_request', 'postReviewComment', 'post_review_comment']
confirmed all 8 auto-generated tools are registered
get_weather(london) [manual]      -> [...]
getWeatherByCity(london) [auto]    -> [...]
confirmed manual and auto-generated tools agree for the same operation
listOpenPullRequests() [auto] -> [...]
getPullRequestDiff(101) [auto] -> [...]
audit_log confirmed for getWeatherByCity: actor='demo-caller'
audit_log confirmed for listOpenPullRequests: actor='demo-caller'
audit_log confirmed for getPullRequestDiff: actor='demo-caller'
```

Note `tools/list` now has 16 entries: the 8 M2 manual tools (snake_case)
plus all 8 M3 auto-generated ones (camelCase operationIds). Only
`get_weather`/`getWeatherByCity` are actually compared for equivalence
above; the manual and generated names never collide because M2 used
snake_case tool keys throughout, and OpenAPI operationIds here are
camelCase.

**❌ Not working if:** `demo-m3` errors with `expected auto-generated tools
missing from tools/list` (mcp-server didn't restart, or didn't pick up the
`ToolSource` rows — check `.run/mcp-server.log` for an
`[openapi-adapter] ...` line confirming it registered them at boot), or an
`AssertionError` on the manual-vs-generated comparison (would mean the
adapter built a tool that doesn't actually behave like the real operation —
a real bug, not a config issue).

**Optional — confirm registration happened at the Postgres level:**

```bash
psql -h <host> -U <user> -d agenticforge -c \
  "SELECT name, kind, openapi_url FROM tool_sources WHERE kind = 'openapi';"
```
Expect two rows: `weather-openapi` and `devops-openapi`.

**Re-running `make demo-m3` later:** safe — `m3_register_openapi_sources.py`
is idempotent (skips ToolSource rows that already exist), and mcp-server
regenerates all tools fresh from the specs on every restart.

### C3. Local (non-container) Python dev loop

Only needed if you're editing service code and want fast iteration without
rebuilding images each time:

```bash
make sync      # uv sync --all-packages --group dev
make lint      # ruff check .
make test      # pytest
```

To run Alembic directly against the Compose Postgres from your host shell
(bypassing the `migrate` container):

```bash
DATABASE_URL=postgresql+psycopg2://agenticforge:agenticforge@localhost:5432/agenticforge \
  uv run --group dev alembic -c migrations/alembic.ini upgrade head
```

### C4. Test M4 — LangGraph agent runtime

M4 brings `orchestrator-worker` online: a real LangGraph agent that calls
your configured LLM, decides whether to invoke an MCP tool, calls it via
`mcp-server` (the exact same M2/M3 tools), loops until done, and traces the
whole thing in Langfuse. Two new pieces of infra are needed beyond M1-M3,
neither containerized for the app services themselves:

1. **Redis** (queue between `orchestrator-api` and `orchestrator-worker`):
   ```bash
   sudo apt-get install -y redis-server
   sudo systemctl start redis-server
   redis-cli ping   # expect: PONG
   ```
2. **Langfuse** — self-hosted via Docker is genuinely easier than natively
   even though the app services stay native (its stack is Postgres +
   ClickHouse + MinIO + Redis):
   ```bash
   make up-langfuse
   ```
   Then open http://localhost:3000, create your first user/org/project, generate
   an API key pair, and set `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env`
   (see step 6 of Path A above for the same one-time setup). Alternative: skip
   Docker entirely and use the Langfuse Cloud free tier, pointing `LANGFUSE_HOST`
   at `https://cloud.langfuse.com` instead.

3. **A model provider configured in `.env`** — M4 hardcodes one provider via
   `M4_MODEL_PROVIDER` (`openai` | `azure_openai` | `anthropic` | `ollama`); the
   full multi-provider model registry is M5. Fill in the matching credentials
   (e.g. `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT`
   for `azure_openai`) — see `.env.example` for the full set per provider.

Then, with `orchestrator-api` and `mcp-server` already running (B6) and the
M2/M3 `ToolSource`/`Tool` rows already registered:

```bash
make demo-m4
```

This starts the mock APIs and `orchestrator-worker` (arq), then runs
`demo/scripts/m4_langgraph_agent_demo.py`, which: registers a reference
`Agent` row (`weather-devops-agent`, `graph_key=supervisor_graph`), submits a
run via `POST /api/v1/runs` asking "What's the weather in London right
now?", polls `GET /api/v1/runs/{id}` until it completes, and prints a
Langfuse trace link.

If you're calling `POST /api/v1/runs` by hand (curl/Postman) rather than via
the demo script, `input` must contain a `message` or `prompt` key — anything
else is rejected with `422` at submission time rather than silently running
the agent on an empty message:
```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "weather-devops-agent", "input": {"message": "What is the weather in Mumbai?"}}'
```

**✅ M4 is working if `demo-m4` ends with something like:**
```
submitted run <uuid>
final run status: completed
output: {'response': "It's 14°C and cloudy in London right now."}
View the trace at: http://localhost:3000/trace/<uuid>
```
Open that link — you should see a trace with a nested LLM generation
(the model deciding to call `get_weather`) and a tool-call span
underneath it, with token usage/cost populated on the generation.

**❌ Not working if:**
- `demo-m4` hangs until it times out (30 polls × 2s) with `status: queued` or
  `running` forever → the worker likely isn't picking up jobs. Check
  `.run/orchestrator-worker.log` — common causes: Redis isn't running
  (`redis-cli ping`), or the worker crashed on startup (missing model
  provider credentials, MCP server unreachable).
- `status: failed` with an `output.error` → check
  `.run/orchestrator-worker.log` for the actual exception. Frequent culprits:
  wrong/missing API key for the configured `M4_MODEL_PROVIDER`, or
  `mcp-server` not running / API key mismatch (the worker mints its own
  `orchestrator-worker` principal key the same way the demo scripts do —
  see `.run/orchestrator_worker_api_key.txt`).
- The trace link 404s in Langfuse → `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` in
  `.env` don't match the project you created in the UI, or Langfuse itself
  isn't up (`make up-langfuse`, then check `docker compose -f
  infra/docker-compose/docker-compose.langfuse.yml ps`).

**Restarting individual pieces while iterating:**
```bash
make stop-native && make run-native   # orchestrator-api + mcp-server
# orchestrator-worker only:
kill $(cat .run/orchestrator-worker.pid); make run-worker-native
```

---

## Troubleshooting

**Path A (Docker):**
- **`docker: permission denied` / `Cannot connect to the Docker daemon`**: your shell session hasn't picked up the `docker` group membership yet — run `newgrp docker` or log out and back in, and confirm with `groups` that `docker` is listed.
- **Docker daemon not running**: `sudo systemctl status docker`; start it with `sudo systemctl enable --now docker` if it's inactive.
- **Port already in use** (`8000`, `8100`, `5432`, `6379`, `3000`, `5433`, `6380`, `8123`, `9090`/`9091`): stop whatever's bound to it (`sudo ss -tulpn | grep <port>`), or edit the `ports:` mapping in `infra/docker-compose/docker-compose.yml` / `docker-compose.langfuse.yml`.
- **`migrate` service fails**: check `docker compose -f infra/docker-compose/docker-compose.yml logs migrate` — almost always either Postgres wasn't healthy yet (rare, there's a `depends_on: condition: service_healthy` guard) or a real schema issue in `migrations/versions/0001_initial_schema.py`.
- **Langfuse web UI errors on first load**: give `langfuse-worker`/`langfuse-clickhouse` a few extra seconds to finish initializing, then refresh — ClickHouse in particular can be slow on first boot.

**Path B (Native):**
- **`CREATE EXTENSION vector` fails with "could not open extension control file"**: the `postgresql-<version>-pgvector` package doesn't match your running server's major version, or didn't install. Re-check `SHOW server_version;` vs. the package you installed.
- **`psql: error: connection refused`**: your existing Postgres isn't listening where you think — check `sudo ss -tulpn | grep 5432` and whether it's bound to `localhost` only vs. all interfaces, and check `pg_hba.conf` allows your user/host.
- **`make demo-m2` fails with a 401/"unauthorized"**: the demo script and the running `mcp-server` must agree on the API key — if you previously deleted `.run/m2_demo_api_key.txt` but the DB row from an earlier run is still there (or vice versa), they'll disagree. Simplest fix: `rm -f .run/m2_demo_api_key.txt` and re-run `make demo-m2` — it'll mint a fresh key and row together.
- **`make demo-m2` fails on `streamablehttp_client`/`ClientSession` import or connection errors**: the MCP Python SDK's client API path can differ between versions — check what's actually installed with `uv run python -c "import mcp.client.streamable_http as m; print(dir(m))"` and adjust the import in `demo/scripts/m2_register_tool_and_call.py` if the function name differs. Also confirm the URL: the script assumes the streamable-http app is mounted at `/mcp` (`MCP_SERVER_URL` in `.env`) — check `.run/mcp-server.log` for the actual mount path if it 404s.
- **`make run-native` starts but `demo-native` fails**: check `.run/orchestrator-api.log` — most likely `DATABASE_URL` in `.env` is wrong, or `make migrate-native` wasn't run first.
- **Port 8000 or 8100 already in use**: something else in your WSL environment (possibly the other datalake project) is already bound to it — change the port in the `make run-native` command / `MCP_SERVER_PORT` in `.env`.
