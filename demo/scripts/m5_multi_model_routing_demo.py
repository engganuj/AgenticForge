"""M5 step 2/2 — verify multi-provider routing.

Exercises the full model_key resolution order (override > routing rule >
agent default) across two runs of the same agent:

  Run 1 (no model_override): the agent is tagged "cost_sensitive"
  (m5_register_model_providers.py), and a routing rule maps that tag to
  claude-haiku-4-5 — so this run should resolve to Claude via the rule, NOT
  the agent's own default_model_key (azure-gpt-5.2-chat).

  Run 2 (model_override="azure-gpt-5.2-chat"): an explicit override should
  win over the routing rule that would otherwise apply — proving override
  takes precedence, not just "some other provider works."

Asserts the two runs actually used different model_keys and that each
matches its expected provider, then prints both Langfuse trace links.

Prerequisites: same as M4 (mock APIs, mcp-server, Postgres, redis,
orchestrator-api, orchestrator-worker all running), plus
m5_register_model_providers.py already run at least once.
"""

import asyncio
import os

import httpx

ORCHESTRATOR_API_URL = os.environ.get("ORCHESTRATOR_API_URL", "http://localhost:8000")
AGENT_NAME = "weather-devops-agent"
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 2


async def submit_and_wait(client: httpx.AsyncClient, *, message: str, model_override: str | None) -> dict:
    body = {"agent_name": AGENT_NAME, "input": {"message": message}}
    if model_override:
        body["model_override"] = model_override

    response = await client.post("/api/v1/runs", json=body)
    response.raise_for_status()
    run_id = response.json()["run_id"]
    print(f"submitted run {run_id} (model_override={model_override!r})")

    run = None
    for _ in range(POLL_ATTEMPTS):
        response = await client.get(f"/api/v1/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    assert run is not None
    assert run["status"] == "completed", f"run did not complete successfully: {run}"
    return run


async def main() -> None:
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_API_URL, timeout=30.0) as client:
        run_via_rule = await submit_and_wait(
            client, message="What's the weather in Mumbai?", model_override=None
        )
        run_via_override = await submit_and_wait(
            client, message="What's the weather in Mumbai?", model_override="azure-gpt-5.2-chat"
        )

    model_key_via_rule = run_via_rule["output"]["model_key"]
    model_key_via_override = run_via_override["output"]["model_key"]

    print(f"run 1 (routing rule) used model_key={model_key_via_rule!r}")
    print(f"run 2 (explicit override) used model_key={model_key_via_override!r}")

    assert model_key_via_rule == "claude-haiku-4-5", (
        f"expected the cost_sensitive routing rule to route to claude-haiku-4-5, got {model_key_via_rule!r}"
    )
    assert model_key_via_override == "azure-gpt-5.2-chat", (
        f"expected the explicit override to win, got {model_key_via_override!r}"
    )
    print("confirmed: routing rule and explicit override both resolved to the correct, different model_keys")

    langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    print(f"trace 1 (via routing rule):    {langfuse_host}/trace/{run_via_rule['langfuse_trace_id']}")
    print(f"trace 2 (via explicit override): {langfuse_host}/trace/{run_via_override['langfuse_trace_id']}")


if __name__ == "__main__":
    asyncio.run(main())
