import uuid
from datetime import datetime, timezone

from agenticforge_shared.db.models import Agent, Run
from agenticforge_shared.db.session import get_session
from agenticforge_shared.model_registry.registry import resolve_model_key
from agenticforge_shared.observability.langfuse_setup import get_langfuse_callback_handler
from agenticforge_shared.schemas.runs import extract_message
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from orchestrator_worker.checkpointer import get_checkpointer
from orchestrator_worker.graphs.supervisor_graph import build_graph

_GRAPH_BUILDERS = {"supervisor_graph": build_graph}


async def run_graph(ctx, run_id: str) -> None:
    run_uuid = uuid.UUID(run_id)

    async with get_session() as session:
        result = await session.execute(select(Run).where(Run.id == run_uuid))
        run = result.scalar_one()
        result = await session.execute(select(Agent).where(Agent.id == run.agent_id))
        agent = result.scalar_one()
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await session.commit()
        user_input = extract_message(run.input) or ""
        graph_key = agent.graph_key
        model_override = run.model_override

    # get_langfuse_callback_handler() returns None if no compatible langfuse
    # SDK import was found (see langfuse_setup.py) — callbacks must stay an
    # empty list in that case, not [None], which LangChain's callback
    # manager rejects.
    langfuse_handler = get_langfuse_callback_handler(trace_id=run_id)
    callbacks = [langfuse_handler] if langfuse_handler is not None else []
    model_key = None

    try:
        graph_builder = _GRAPH_BUILDERS.get(graph_key)
        if graph_builder is None:
            raise ValueError(f"unknown graph_key: {graph_key!r}")

        model_key = await resolve_model_key(agent, model_override)

        async with get_checkpointer() as checkpointer:
            graph = await graph_builder(checkpointer, model_key)
            result_state = await graph.ainvoke(
                {"messages": [HumanMessage(content=user_input)]},
                config={
                    "configurable": {"thread_id": run_id},
                    "callbacks": callbacks,
                },
            )
        final_message = result_state["messages"][-1]
        output = {"response": final_message.content, "model_key": model_key}
        status = "completed"
    except Exception as exc:  # noqa: BLE001 — surface any failure into the Run row, not just arq's logs
        output = {"error": str(exc)}
        status = "failed"

    async with get_session() as session:
        result = await session.execute(select(Run).where(Run.id == run_uuid))
        run = result.scalar_one()
        run.status = status
        run.output = output
        run.langfuse_trace_id = run_id if langfuse_handler is not None else None
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
