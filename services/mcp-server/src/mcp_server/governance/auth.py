import contextvars
import os

from agenticforge_shared.db.models import ApiKey
from agenticforge_shared.db.session import get_session
from agenticforge_shared.rbac.api_keys import hash_api_key
from sqlalchemy import select

REQUIRE_AUTH = os.environ.get("MCP_REQUIRE_AUTH", "true").lower() == "true"

# Set by ApiKeyAuthMiddleware per-request, read by tool implementations that
# want to attribute an audit log entry to the calling principal. Relies on
# the ASGI call chain staying on one asyncio task, which holds for FastMCP's
# streamable-http request handling.
current_principal: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_principal", default=None
)


class ApiKeyAuthMiddleware:
    """Plain ASGI middleware — wraps the MCP Starlette app directly rather
    than going through Starlette's add_middleware(), so it doesn't depend on
    exactly how/when FastMCP builds its middleware stack.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not REQUIRE_AUTH:
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        auth_header = headers.get(b"authorization", b"").decode()
        if not auth_header.startswith("Bearer "):
            await _send_unauthorized(send, "missing bearer token")
            return

        raw_key = auth_header.removeprefix("Bearer ").strip()
        principal = await _resolve_principal(raw_key)
        if principal is None:
            await _send_unauthorized(send, "invalid or revoked api key")
            return

        token = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)


async def _resolve_principal(raw_key: str) -> str | None:
    hashed = hash_api_key(raw_key)
    async with get_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.hashed_key == hashed, ApiKey.revoked_at.is_(None))
        )
        api_key = result.scalar_one_or_none()
        return api_key.principal_name if api_key else None


async def _send_unauthorized(send, detail: str) -> None:
    body = f'{{"error": "unauthorized", "detail": "{detail}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
