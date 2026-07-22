"""M3 step 2/2 — verify the OpenAPI-to-MCP adapter.

Assumes m3_register_openapi_sources.py has already run AND mcp-server has
been (re)started since (both handled automatically by `make demo-m3`).

Checks:
1. tools/list includes the auto-generated tools (camelCase operationIds),
   alongside the M2 manual tools (snake_case) — no naming collisions by
   construction, so both sets coexist.
2. Calls the auto-generated `getWeatherByCity` and the M2 hand-written
   `get_weather` for the same city, and asserts they return the same data —
   proving the adapter produces a functionally equivalent tool for an
   operation M2 already hand-wrote, without any adapter-specific code path.
3. Calls two auto-generated DevOps tools directly (list + get-diff), showing
   generation works across multiple operations/methods, not just one.
4. Confirms audit_log rows exist for the generated-tool calls too — the
   audit/auth path is shared with manual tools, not bypassed by codegen.
"""

import asyncio
import os
import sys
from pathlib import Path

from agenticforge_shared.db.models import AuditLog
from agenticforge_shared.db.session import get_session
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ensure_api_key  # noqa: E402

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100/mcp")

GENERATED_TOOLS = {
    "getWeatherByCity",
    "listOpenPullRequests",
    "getPullRequestDiff",
    "postReviewComment",
    "getTestRunStatus",
    "createBranch",
    "commitFileChange",
    "openPullRequest",
}


async def main() -> None:
    async with get_session() as session:
        raw_key = await ensure_api_key(session)
        await session.commit()

    async with streamablehttp_client(
        MCP_SERVER_URL, headers={"Authorization": f"Bearer {raw_key}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            print("tools/list ->", sorted(tool_names))

            missing = GENERATED_TOOLS - tool_names
            assert not missing, (
                f"expected auto-generated tools missing from tools/list: {missing} — "
                "did you run m3_register_openapi_sources.py and restart mcp-server?"
            )
            print(f"confirmed all {len(GENERATED_TOOLS)} auto-generated tools are registered")

            manual_result = await session.call_tool("get_weather", {"city": "london"})
            generated_result = await session.call_tool("getWeatherByCity", {"city": "london"})
            print("get_weather(london) [manual]      ->", manual_result.content)
            print("getWeatherByCity(london) [auto]    ->", generated_result.content)
            assert manual_result.content == generated_result.content, (
                "manual and auto-generated weather tools returned different results "
                "for the same input — adapter output doesn't match the hand-written tool"
            )
            print("confirmed manual and auto-generated tools agree for the same operation")

            prs = await session.call_tool("listOpenPullRequests", {})
            print("listOpenPullRequests() [auto] ->", prs.content)
            diff = await session.call_tool("getPullRequestDiff", {"pr_id": "101"})
            print("getPullRequestDiff(101) [auto] ->", diff.content)

    async with get_session() as session:
        for tool_key in ("getWeatherByCity", "listOpenPullRequests", "getPullRequestDiff"):
            result = await session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "tool", AuditLog.resource_id == tool_key)
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
            entry = result.scalar_one_or_none()
            assert entry is not None, f"expected an audit_log row for auto-generated tool {tool_key}"
            print(f"audit_log confirmed for {tool_key}: actor={entry.actor!r}")


if __name__ == "__main__":
    asyncio.run(main())
