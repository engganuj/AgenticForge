"""Reference LangGraph implementation: a minimal agent-node + tools-node
loop (single agent, not yet a multi-agent supervisor/handoff mesh — that
shape is a StateGraph extension, not a rewrite, whenever it's needed). Tools
come from mcp-server (M2/M3's tools) via langchain-mcp-adapters, over the
same Streamable HTTP + API-key auth path any other MCP client uses.

Model resolution goes through the model registry (M5,
agenticforge_shared.model_registry.registry) — build_graph() takes an
already-resolved `model_key`, not a provider name. Which model_key to use
(override / routing rule / agent default) is decided by the caller
(orchestrator_worker.tasks) before build_graph() is invoked.
"""

import os
from pathlib import Path
from typing import Annotated, TypedDict

from agenticforge_shared.db.session import get_session
from agenticforge_shared.model_registry.registry import get_chat_model
from agenticforge_shared.rbac.bootstrap import ensure_api_key
from langchain_core.messages import AnyMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

WORKER_KEY_FILE = Path(".run/orchestrator_worker_api_key.txt")


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def _get_worker_api_key() -> str:
    async with get_session() as session:
        key = await ensure_api_key(session, WORKER_KEY_FILE, "orchestrator-worker", role_name="operator")
        await session.commit()
        return key


async def _get_mcp_tools() -> list:
    # If your installed langchain-mcp-adapters version's MultiServerMCPClient
    # constructor/config shape differs, check
    # `python -c "from langchain_mcp_adapters.client import MultiServerMCPClient; help(MultiServerMCPClient)"`.
    mcp_server_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8100/mcp")
    api_key = await _get_worker_api_key()
    client = MultiServerMCPClient(
        {
            "agenticforge": {
                "url": mcp_server_url,
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {api_key}"},
            }
        }
    )
    return await client.get_tools()


async def build_graph(checkpointer, model_key: str):
    model = await get_chat_model(model_key)
    tools = await _get_mcp_tools()
    model_with_tools = model.bind_tools(tools)

    async def agent_node(state: AgentState) -> dict:
        response = await model_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)
