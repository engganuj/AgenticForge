"""Shared seeding helpers for the per-milestone demo scripts. Not a package
entrypoint on its own — imported by demo/scripts/m2_*.py and m3_*.py.

Delegates to agenticforge_shared.rbac.bootstrap, which orchestrator-worker
(M4) also uses for its own service-principal key — this module just pins the
demo-caller key file path or the demo scripts.
"""

from pathlib import Path

from agenticforge_shared.rbac.bootstrap import ensure_api_key as _ensure_api_key
from agenticforge_shared.rbac.bootstrap import ensure_role  # noqa: F401 (re-exported)

KEY_FILE = Path(__file__).resolve().parents[2] / ".run" / "m2_demo_api_key.txt"


async def ensure_api_key(session, principal_name: str = "demo-caller") -> str:
    """Reuses the same demo-caller API key/file across all M2/M3 demo scripts."""
    return await _ensure_api_key(session, KEY_FILE, principal_name, role_name="operator")
