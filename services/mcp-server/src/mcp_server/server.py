import asyncio
import os

import uvicorn
from mcp.server.fastmcp import FastMCP

from mcp_server.governance.auth import ApiKeyAuthMiddleware

mcp = FastMCP("AgenticForge MCP Server")

# Tool modules register themselves against `mcp` via the @mcp.tool() decorator
# as a side effect of being imported. Import must happen after `mcp` exists
# above (each tool module does `from mcp_server.server import mcp`), and
# before the app is served below.
from mcp_server.tools import demo_weather, devops  # noqa: E402,F401


def create_app():
    return ApiKeyAuthMiddleware(mcp.streamable_http_app())


async def _register_openapi_tool_sources() -> None:
    """M3: at boot, register one MCP tool per operation for every enabled
    ToolSource(kind="openapi"). Boot-time, not hot-reload — see
    adapters/openapi_adapter.py docstring for why.
    """
    from agenticforge_shared.db.models import ToolSource
    from agenticforge_shared.db.session import get_session
    from sqlalchemy import select

    from mcp_server.adapters.openapi_adapter import fetch_openapi_spec, register_tools_from_openapi

    async with get_session() as session:
        result = await session.execute(
            select(ToolSource).where(ToolSource.kind == "openapi", ToolSource.enabled.is_(True))
        )
        tool_sources = result.scalars().all()

    for tool_source in tool_sources:
        spec = await fetch_openapi_spec(tool_source.openapi_url)
        registered = register_tools_from_openapi(
            spec, base_url=tool_source.base_url_override, auth_config=tool_source.auth_config
        )
        print(f"[openapi-adapter] {tool_source.name}: registered {len(registered)} tools -> {registered}")


# Registration must happen before `app` is built below, and at module level
# (not inside main()) so it still runs if uvicorn re-imports this module by
# string reference in a reload/multi-worker context, where main() itself
# wouldn't be re-invoked. Single-process/no-reload today (see main()), so in
# practice this only ever runs once — but this ordering keeps it correct if
# that changes later.
asyncio.run(_register_openapi_tool_sources())

# Create the app at module level so it's available when uvicorn imports by
# string reference (required for future --reload/multi-worker support).
app = create_app()


def main() -> None:
    port = int(os.environ.get("MCP_SERVER_PORT", "8100"))
    uvicorn.run("mcp_server.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
