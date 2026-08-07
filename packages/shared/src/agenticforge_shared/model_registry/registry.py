"""Model registry (M5): resolves a logical `model_key` to an actual
LangChain chat model instance, and resolves *which* model_key an agent run
should use (explicit override > matching routing rule > agent default).

Both lookups hit Postgres fresh on every call rather than caching — a new
ModelProvider/ModelRegistryEntry/ModelRoutingRule row takes effect on the
very next run, no orchestrator-worker restart needed (unlike M3's boot-time
OpenAPI tool registration, which is a different tradeoff for a different
reason — see openapi_adapter.py).
"""

import os

from sqlalchemy import select

from agenticforge_shared.db.models import Agent, ModelProvider, ModelRegistryEntry, ModelRoutingRule
from agenticforge_shared.db.session import get_session


def _resolve_secret(auth_secret_ref: str | None) -> str | None:
    """auth_secret_ref is the *name* of an env var holding the real secret,
    never the secret itself — the schema's "secret refs, never raw secrets"
    rule, kept pragmatic (env var lookup) until a real secrets manager is
    wired in (M8 governance scope).
    """
    if not auth_secret_ref:
        return None
    return os.environ.get(auth_secret_ref)


def build_chat_model(provider: ModelProvider, entry: ModelRegistryEntry):
    api_key = _resolve_secret(provider.auth_secret_ref)
    config = provider.config or {}

    if provider.provider_type == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=provider.base_url,
            azure_deployment=entry.model_name,
            api_key=api_key,
            api_version=config.get("api_version", os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview")),
        )

    if provider.provider_type == "openai":
        from langchain_openai import ChatOpenAI

        kwargs = {"model": entry.model_name, "api_key": api_key}
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        return ChatOpenAI(**kwargs)

    if provider.provider_type == "anthropic":
        # Covers both native Anthropic (base_url unset) and Claude via Azure
        # AI Foundry's Anthropic-compatible endpoint (base_url set) — same
        # client, same protocol, just a different base_url.
        from langchain_anthropic import ChatAnthropic

        kwargs = {"model": entry.model_name, "api_key": api_key}
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        return ChatAnthropic(**kwargs)

    if provider.provider_type == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=entry.model_name, base_url=provider.base_url or "http://localhost:11434")

    if provider.provider_type == "vllm":
        # vLLM exposes an OpenAI-compatible endpoint.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=entry.model_name, api_key=api_key or "not-needed", base_url=provider.base_url)

    raise ValueError(f"unsupported provider_type: {provider.provider_type!r}")


async def get_chat_model(model_key: str):
    async with get_session() as session:
        result = await session.execute(
            select(ModelRegistryEntry, ModelProvider)
            .join(ModelProvider, ModelRegistryEntry.provider_id == ModelProvider.id)
            .where(ModelRegistryEntry.model_key == model_key)
        )
        row = result.first()

    if row is None:
        raise ValueError(f"no model_registry entry for model_key={model_key!r}")

    entry, provider = row
    return build_chat_model(provider, entry)


async def resolve_model_key(agent: Agent, model_override: str | None) -> str:
    """Resolution order: explicit override > first matching routing rule
    (by descending priority) > agent's own default_model_key.
    """
    if model_override:
        return model_override

    async with get_session() as session:
        result = await session.execute(select(ModelRoutingRule).order_by(ModelRoutingRule.priority.desc()))
        rules = result.scalars().all()

    agent_tags = (agent.config or {}).get("tags", [])
    for rule in rules:
        tag = (rule.match_condition or {}).get("agent_tag")
        if tag and tag in agent_tags:
            return rule.target_model_key

    return agent.default_model_key
