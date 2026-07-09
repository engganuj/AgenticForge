import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "AgenticForge MCP Server",
    host="0.0.0.0",
    port=int(os.environ.get("MCP_SERVER_PORT", "8100")),
)

# Tools are registered by importing modules under mcp_server.tools and
# mcp_server.adapters (OpenAPI-generated tools) — none registered yet in M1.
# `mcp.run(transport="streamable-http")` below serves an empty `tools/list`
# until M2 adds the first manually-defined tool.


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
