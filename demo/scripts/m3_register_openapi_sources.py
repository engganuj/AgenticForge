"""M3 step 1/2 — register ToolSource(kind="openapi") rows for the demo APIs.

Idempotent: safe to re-run. Registration itself only takes effect once
mcp-server is (re)started, since M3's adapter runs at boot time, not via
hot-reload (see mcp_server/adapters/openapi_adapter.py docstring for why).
`make demo-m3` runs this, then restarts mcp-server, then runs
m3_openapi_adapter_demo.py automatically — see the Makefile if running these
steps by hand.
"""

import asyncio
import os

from agenticforge_shared.db.models import ToolSource
from agenticforge_shared.db.session import get_session
from sqlalchemy import select

DEMO_API_BASE_URL = os.environ.get("DEMO_API_BASE_URL", "http://localhost:9000")
DEVOPS_API_BASE_URL = os.environ.get("DEVOPS_API_BASE_URL", "http://localhost:9001")

_SOURCES = [
    {
        "name": "weather-openapi",
        "kind": "openapi",
        "openapi_url": f"{DEMO_API_BASE_URL}/openapi.json",
        "base_url_override": DEMO_API_BASE_URL,
    },
    {
        "name": "devops-openapi",
        "kind": "openapi",
        "openapi_url": f"{DEVOPS_API_BASE_URL}/openapi.json",
        "base_url_override": DEVOPS_API_BASE_URL,
    },
]


async def main() -> None:
    async with get_session() as session:
        for spec in _SOURCES:
            result = await session.execute(select(ToolSource).where(ToolSource.name == spec["name"]))
            if result.scalar_one_or_none() is None:
                session.add(ToolSource(**spec))
                print(f"registered ToolSource: {spec['name']} -> {spec['openapi_url']}")
            else:
                print(f"ToolSource already exists, skipping: {spec['name']}")
        await session.commit()

    print("Done. Restart mcp-server so it picks these up (make restart-mcp-native).")


if __name__ == "__main__":
    asyncio.run(main())
