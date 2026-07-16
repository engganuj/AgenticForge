"""Manually-registered MCP tool wrapping the demo weather API (M2). The
equivalent OpenAPI-driven registration path lands in M3.
"""

import os

import httpx

from mcp_server.governance.audit import record_tool_call
from mcp_server.governance.auth import current_principal
from mcp_server.server import mcp

DEMO_API_BASE_URL = os.environ.get("DEMO_API_BASE_URL", "http://localhost:9000")


@mcp.tool()
async def get_weather(city: str) -> dict:
    """Get current mock weather for a city from the demo weather API."""
    async with httpx.AsyncClient(base_url=DEMO_API_BASE_URL, timeout=10.0) as client:
        response = await client.get(f"/weather/{city}")
        response.raise_for_status()
        result = response.json()

    await record_tool_call(
        tool_key="get_weather",
        input_={"city": city},
        output=result,
        actor=current_principal.get(),
    )
    return result
