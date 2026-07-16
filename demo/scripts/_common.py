"""Shared seeding helpers for the per-milestone demo scripts. Not a package
entrypoint on its own — imported by demo/scripts/m2_*.py.
"""

from pathlib import Path

from agenticforge_shared.db.models import ApiKey, Role
from agenticforge_shared.rbac.api_keys import generate_api_key, hash_api_key
from sqlalchemy import select

KEY_FILE = Path(__file__).resolve().parents[2] / ".run" / "m2_demo_api_key.txt"


async def ensure_role(session, name: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name=name)
        session.add(role)
        await session.flush()
    return role


async def ensure_api_key(session, principal_name: str = "demo-caller") -> str:
    """Reuses the same demo-caller API key/file across all M2 demo scripts."""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        raw_key = KEY_FILE.read_text().strip()
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.hashed_key == hash_api_key(raw_key), ApiKey.revoked_at.is_(None)
            )
        )
        if result.scalar_one_or_none() is not None:
            return raw_key

    role = await ensure_role(session, "operator")
    raw_key = generate_api_key()
    session.add(
        ApiKey(hashed_key=hash_api_key(raw_key), role_id=role.id, principal_name=principal_name)
    )
    await session.flush()
    KEY_FILE.write_text(raw_key)
    return raw_key
