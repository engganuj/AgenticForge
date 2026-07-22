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


# Create the app at module level so it's available when uvicorn imports
app = create_app()


def main() -> None:
    port = int(os.environ.get("MCP_SERVER_PORT", "8100"))
    uvicorn.run("mcp_server.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
