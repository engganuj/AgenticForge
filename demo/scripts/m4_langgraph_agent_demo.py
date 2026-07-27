"""M4 demo/smoke-test — LangGraph agent runtime.

Ensures a reference Agent row exists, submits a run through
`orchestrator-api` (`POST /api/v1/runs`), polls `GET /api/v1/runs/{id}`
until it completes, and points you at the resulting Langfuse trace. The
input prompt ("What's the weather in London?") is chosen to make the model
call the `get_weather` MCP tool, so a successful run exercises the full
agent -> MCP -> tool -> Langfuse path end-to-end, not just a plain chat
completion.

Prerequisites (native/Path B — see INSTALL.md):
    uv run python demo/mock_api/main.py           # :9000
    uv run python demo/mock_devops_api/main.py    # :9001
    uv run python -m mcp_server.server             # :8100
    docker compose -f infra/docker-compose/docker-compose.langfuse.yml up -d
    sudo systemctl start redis-server              # or: redis-server --daemonize yes
    uv run uvicorn orchestrator_api.main:app --host 0.0.0.0 --port 8000
    uv run arq orchestrator_worker.worker.WorkerSettings
"""

import asyncio
import os

import httpx
from agenticforge_shared.db.models import Agent
from agenticforge_shared.db.session import get_session
from sqlalchemy import select

ORCHESTRATOR_API_URL = os.environ.get("ORCHESTRATOR_API_URL", "http://localhost:8000")
AGENT_NAME = "weather-devops-agent"
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 2


async def ensure_agent(session) -> None:
    result = await session.execute(select(Agent).where(Agent.name == AGENT_NAME))
    if result.scalar_one_or_none() is None:
        session.add(
            Agent(
                name=AGENT_NAME,
                description="M4 reference agent: supervisor loop over the M2/M3 MCP tools",
                graph_key="supervisor_graph",
                default_model_key=f"{os.environ.get('M4_MODEL_PROVIDER', 'openai')}:demo",
                config={},
            )
        )


async def main() -> None:
    async with get_session() as session:
        await ensure_agent(session)
        await session.commit()

    async with httpx.AsyncClient(base_url=ORCHESTRATOR_API_URL, timeout=30.0) as client:
        response = await client.post(
            "/api/v1/runs",
            json={
                "agent_name": AGENT_NAME,
                "input": {"message": "What's the weather in London right now?"},
            },
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]
        print(f"submitted run {run_id}")

        run = None
        for _ in range(POLL_ATTEMPTS):
            response = await client.get(f"/api/v1/runs/{run_id}")
            response.raise_for_status()
            run = response.json()
            if run["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    assert run is not None
    print("final run status:", run["status"])
    print("output:", run["output"])
    assert run["status"] == "completed", f"run did not complete successfully: {run}"

    langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    print(f"View the trace at: {langfuse_host}/trace/{run['langfuse_trace_id']}")


if __name__ == "__main__":
    asyncio.run(main())
