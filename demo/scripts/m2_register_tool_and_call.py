"""M2 demo/smoke-test.

1. Ensures an API key + role exist for a "demo-caller" principal (persisted
   locally so re-runs reuse the same key rather than piling up new rows).
2. Registers the manual `get_weather` tool's bookkeeping rows (ToolSource,
   Tool) — the tool implementation itself is hardcoded in
   mcp_server.tools.demo_weather; this just makes it visible in the registry.
3. Connects to the running MCP server as a client, lists tools, calls
   get_weather, and asserts a matching audit_log row was written.

Prerequisites (all native/Path B — see INSTALL.md):
    uv run python demo/mock_api/main.py      # demo weather API on :9000
    uv run python -m mcp_server.server        # MCP server on :8100
"""

import asyncio
import os
import sys
from pathlib import Path

from agenticforge_shared.db.models import AuditLog, Tool, ToolSource
from agenticforge_shared.db.session import get_session
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import KEY_FILE, ensure_api_key  # noqa: E402

# If your installed `mcp` SDK mounts the streamable-http app at a different
# path than "/mcp", override via the MCP_SERVER_URL env var.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100/mcp")


async def ensure_tool_registration(session) -> None:
    result = await session.execute(select(ToolSource).where(ToolSource.name == "demo-weather-api"))
    tool_source = result.scalar_one_or_none()
    if tool_source is None:
        tool_source = ToolSource(
            name="demo-weather-api",
            kind="manual",
            base_url_override=os.environ.get("DEMO_API_BASE_URL", "http://localhost:9000"),
        )
        session.add(tool_source)
        await session.flush()

    result = await session.execute(select(Tool).where(Tool.tool_key == "get_weather"))
    if result.scalar_one_or_none() is None:
        session.add(
            Tool(
                tool_source_id=tool_source.id,
                tool_key="get_weather",
                display_name="Get Weather",
                input_schema={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
        )


async def main() -> None:
    async with get_session() as session:
        raw_key = await ensure_api_key(session)
        await ensure_tool_registration(session)
        await session.commit()

    print(f"Using API key for principal 'demo-caller' (stored at {KEY_FILE})")

    async with streamablehttp_client(
        MCP_SERVER_URL, headers={"Authorization": f"Bearer {raw_key}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools/list ->", [t.name for t in tools.tools])

            result = await session.call_tool("get_weather", {"city": "london"})
            print("tools/call get_weather(london) ->", result.content)

    async with get_session() as session:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "tool", AuditLog.resource_id == "get_weather")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        entry = result.scalar_one_or_none()
        assert entry is not None, "expected an audit_log row for the get_weather tool call"
        print(f"audit_log confirmed: actor={entry.actor!r} action={entry.action!r} after={entry.after!r}")


if __name__ == "__main__":
    asyncio.run(main())
