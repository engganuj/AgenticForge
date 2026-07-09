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
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `AZURE_OPENAI_*` | M5 (model registry) | Leave blank if you're not using that provider yet |
| `OLLAMA_BASE_URL` / `VLLM_BASE_URL` | M5, local/open models | Only if you're running Ollama/vLLM locally |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | M4+ (tracing) | You generate these in step 6 below, *after* Langfuse is up — leave blank for now |

## 4. Bring up the stack

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
list at this stage.

## 8. Local (non-container) Python dev loop

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

## 9. Tear down / reset

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

### B7. Check the MCP server directly (optional)

```bash
npx @modelcontextprotocol/inspector http://localhost:8100
```
`tools/list` should return an empty list at this stage (M1 has no tools yet).

### B8. When you reach M4 (Langfuse tracing, queue-backed runs)

At that point you'll need Redis and Langfuse too. Cheapest options then:
- Redis: `sudo apt-get install -y redis-server` (native, no Docker needed for this one either)
- Langfuse: either self-host at that point (its stack — ClickHouse, MinIO, Postgres, Redis — is genuinely easier via `docker-compose.langfuse.yml` than natively, even if you're avoiding Docker for the app services), or sign up for the Langfuse Cloud free tier and point `LANGFUSE_HOST`/keys at that instead of self-hosting.

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
- **`make run-native` starts but `demo-native` fails**: check `.run/orchestrator-api.log` — most likely `DATABASE_URL` in `.env` is wrong, or `make migrate-native` wasn't run first.
- **Port 8000 or 8100 already in use**: something else in your WSL environment (possibly the other datalake project) is already bound to it — change the port in the `make run-native` command / `MCP_SERVER_PORT` in `.env`.
