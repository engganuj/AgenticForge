"""M5 step 1/2 — seed the model registry.

Registers two real providers (reading connection info from env vars, never
hardcoding secrets into this file): the Azure OpenAI deployment M4 already
used, and Claude via Azure AI Foundry's Anthropic-compatible endpoint. Also
seeds one routing rule and retags the M4 reference agent so the M5 demo can
exercise the full resolution order (override > rule > default) — see
m5_multi_model_routing_demo.py.

Idempotent: safe to re-run. No mcp-server/orchestrator-worker restart
needed afterward — the registry is read fresh on every run (unlike M3's
boot-time OpenAPI tool registration).
"""

import asyncio
import os

from agenticforge_shared.db.models import Agent, ModelProvider, ModelRegistryEntry, ModelRoutingRule
from agenticforge_shared.db.session import get_session
from sqlalchemy import select

AGENT_NAME = "weather-devops-agent"  # the M4 reference agent

AZURE_OPENAI_MODEL_KEY = "azure-gpt-5.2-chat"
CLAUDE_MODEL_KEY = "claude-haiku-4-5"


async def ensure_provider(session, **fields) -> ModelProvider:
    result = await session.execute(select(ModelProvider).where(ModelProvider.name == fields["name"]))
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = ModelProvider(**fields)
        session.add(provider)
        await session.flush()
    else:
        for key, value in fields.items():
            setattr(provider, key, value)
    return provider


async def ensure_model(session, provider: ModelProvider, **fields) -> ModelRegistryEntry:
    result = await session.execute(select(ModelRegistryEntry).where(ModelRegistryEntry.model_key == fields["model_key"]))
    entry = result.scalar_one_or_none()
    if entry is None:
        session.add(ModelRegistryEntry(provider_id=provider.id, **fields))
    else:
        entry.provider_id = provider.id
        for key, value in fields.items():
            setattr(entry, key, value)
    return entry


async def ensure_routing_rule(session, **fields) -> None:
    result = await session.execute(
        select(ModelRoutingRule).where(ModelRoutingRule.target_model_key == fields["target_model_key"])
    )
    if result.scalar_one_or_none() is None:
        session.add(ModelRoutingRule(**fields))


async def main() -> None:
    async with get_session() as session:
        azure_openai = await ensure_provider(
            session,
            name="azure-openai",
            provider_type="azure_openai",
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            auth_secret_ref="AZURE_OPENAI_API_KEY",
            config={"api_version": os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview")},
        )
        await ensure_model(
            session,
            azure_openai,
            model_key=AZURE_OPENAI_MODEL_KEY,
            model_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            model_type="chat",
            is_default=True,
            tags=["general"],
        )

        azure_foundry_anthropic = await ensure_provider(
            session,
            name="azure-foundry-anthropic",
            provider_type="anthropic",
            base_url=os.environ["AZURE_AI_FOUNDRY_ANTHROPIC_ENDPOINT"],
            auth_secret_ref="AZURE_AI_FOUNDRY_ANTHROPIC_API_KEY",
            config={},
        )
        await ensure_model(
            session,
            azure_foundry_anthropic,
            model_key=CLAUDE_MODEL_KEY,
            model_name=os.environ["AZURE_AI_FOUNDRY_ANTHROPIC_DEPLOYMENT"],
            model_type="chat",
            is_default=False,
            tags=["cost_sensitive", "fast"],
        )

        await ensure_routing_rule(
            session,
            match_condition={"agent_tag": "cost_sensitive"},
            target_model_key=CLAUDE_MODEL_KEY,
            priority=10,
        )

        result = await session.execute(select(Agent).where(Agent.name == AGENT_NAME))
        agent = result.scalar_one_or_none()
        if agent is not None:
            agent.default_model_key = AZURE_OPENAI_MODEL_KEY
            agent.config = {**(agent.config or {}), "tags": ["cost_sensitive"]}

        await session.commit()

    print(f"registered providers: azure-openai -> {AZURE_OPENAI_MODEL_KEY}, azure-foundry-anthropic -> {CLAUDE_MODEL_KEY}")
    print("registered routing rule: agent_tag=cost_sensitive -> claude-haiku-4-5")
    if agent is not None:
        print(f"updated agent {AGENT_NAME!r}: default_model_key={AZURE_OPENAI_MODEL_KEY!r}, tags=['cost_sensitive']")
    else:
        print(f"note: agent {AGENT_NAME!r} doesn't exist yet — run demo-m4 first, or it'll be created on next m4 demo run")


if __name__ == "__main__":
    asyncio.run(main())
