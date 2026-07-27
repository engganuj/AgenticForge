"""M4 reference LangGraph implementation: a minimal agent-node + tools-node
loop (single agent, not yet a multi-agent supervisor/handoff mesh — that
shape is a StateGraph extension, not a rewrite, whenever it's needed). Tools
come from mcp-server (M2/M3's tools) via langchain-mcp-adapters, over the
same Streamable HTTP + API-key auth path any other MCP client uses.

Model provider is hardcoded per M4_MODEL_PROVIDER for now — the full
model_registry/routing-rules indirection is M5. Swapping providers later is
a change inside _get_chat_model(), not a graph rewrite.
"""

import os
from pathlib import Path
from typing import Annotated, TypedDict

from agenticforge_shared.db.session import get_session
from agenticforge_shared.rbac.bootstrap import ensure_api_key
from langchain_core.messages import AnyMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

WORKER_KEY_FILE = Path(".run/orchestrator_worker_api_key.txt")


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _get_chat_model():
    provider = os.environ.get("M4_MODEL_PROVIDER", "openai")

    if provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview"),
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"))
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=os.environ.get("OLLAMA_MODEL", "llama3"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), api_key=os.environ["OPENAI_API_KEY"])


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


async def build_graph(checkpointer):
    model = _get_chat_model()
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
