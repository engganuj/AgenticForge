"""Bootstrap helper for minting/reusing a role-scoped API key for a given
principal, backed by a local key file so re-runs/restarts reuse the same
key rather than piling up new rows. Used by both the demo scripts (M2/M3)
and orchestrator-worker (M4, for its service-to-service calls into
mcp-server) — genuinely shared infrastructure, not demo-only.

Real per-service credential provisioning/rotation (secrets manager, etc.) is
M8 governance scope; this is the pragmatic bootstrap in the meantime.
"""

from pathlib import Path

from sqlalchemy import select

from agenticforge_shared.db.models import ApiKey, Role
from agenticforge_shared.rbac.api_keys import generate_api_key, hash_api_key


async def ensure_role(session, name: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name=name)
        session.add(role)
        await session.flush()
    return role


async def ensure_api_key(
    session, key_file: Path, principal_name: str, role_name: str = "operator"
) -> str:
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        raw_key = key_file.read_text().strip()
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.hashed_key == hash_api_key(raw_key), ApiKey.revoked_at.is_(None)
            )
        )
        if result.scalar_one_or_none() is not None:
            return raw_key

    role = await ensure_role(session, role_name)
    raw_key = generate_api_key()
    session.add(
        ApiKey(hashed_key=hash_api_key(raw_key), role_id=role.id, principal_name=principal_name)
    )
    await session.flush()
    key_file.write_text(raw_key)
    return raw_key
