from agenticforge_shared.db.models import AuditLog
from agenticforge_shared.db.session import get_session


async def record_tool_call(
    tool_key: str, input_: dict, output: dict, actor: str | None = None
) -> None:
    async with get_session() as session:
        session.add(
            AuditLog(
                actor=actor or "unknown",
                action="tool_call",
                resource_type="tool",
                resource_id=tool_key,
                before={"input": input_},
                after={"output": output},
            )
        )
        await session.commit()
