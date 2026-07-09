"""Single shared SQLAlchemy schema for AgenticForge (orchestrator, MCP server, ingestion).

Langfuse and LangGraph's checkpointer manage their own tables (in the same
Postgres instance, but not modeled here) — see AsyncPostgresSaver.setup()
for `checkpoints`/`checkpoint_writes` and the Langfuse compose stack for its
own schema.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # matches BAAI/bge-large-en-v1.5; change if the default embedding model changes


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Agents & workflows
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    graph_key: Mapped[str] = mapped_column(String(255))
    default_model_key: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    owner: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()

    agent_tools: Mapped[list["AgentTool"]] = relationship(back_populates="agent")


class AgentTool(Base):
    __tablename__ = "agent_tools"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True
    )

    agent: Mapped["Agent"] = relationship(back_populates="agent_tools")
    tool: Mapped["Tool"] = relationship(back_populates="agent_tools")


# ---------------------------------------------------------------------------
# Tools / MCP
# ---------------------------------------------------------------------------


class ToolSource(Base):
    __tablename__ = "tool_sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(50))  # openapi | manual | sql_semantic | rag | code_exec
    openapi_url: Mapped[str | None] = mapped_column(Text)
    base_url_override: Mapped[str | None] = mapped_column(Text)
    auth_config: Mapped[dict] = mapped_column(JSONB, default=dict)  # secret refs, never raw secrets
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created_at()

    tools: Mapped[list["Tool"]] = relationship(back_populates="tool_source")
    credentials: Mapped[list["ToolCredential"]] = relationship(back_populates="tool_source")


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tool_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_sources.id", ondelete="CASCADE")
    )
    tool_key: Mapped[str] = mapped_column(String(255), unique=True)  # MCP tool name
    display_name: Mapped[str] = mapped_column(String(255))
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    pii_policy: Mapped[str] = mapped_column(String(20), default="mask")  # mask | block | allow
    cost_hint: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = _created_at()

    tool_source: Mapped["ToolSource"] = relationship(back_populates="tools")
    agent_tools: Mapped[list["AgentTool"]] = relationship(back_populates="tool")


class ToolCredential(Base):
    __tablename__ = "tool_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tool_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_sources.id", ondelete="CASCADE")
    )
    secret_ref: Mapped[str] = mapped_column(Text)  # pointer into secrets manager / encrypted column
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    tool_source: Mapped["ToolSource"] = relationship(back_populates="credentials")


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True)
    provider_type: Mapped[str] = mapped_column(String(50))  # openai | anthropic | azure_openai | ollama | vllm
    base_url: Mapped[str | None] = mapped_column(Text)
    auth_secret_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    models: Mapped[list["ModelRegistryEntry"]] = relationship(back_populates="provider")


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = _uuid_pk()
    model_key: Mapped[str] = mapped_column(String(255), unique=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"))
    model_name: Mapped[str] = mapped_column(String(255))
    model_type: Mapped[str] = mapped_column(String(20))  # chat | embedding
    context_window: Mapped[int | None] = mapped_column(Integer)
    cost_per_1k_input: Mapped[float | None] = mapped_column(Numeric(10, 6))
    cost_per_1k_output: Mapped[float | None] = mapped_column(Numeric(10, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime] = _created_at()

    provider: Mapped["ModelProvider"] = relationship(back_populates="models")


class ModelRoutingRule(Base):
    __tablename__ = "model_routing_rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    match_condition: Mapped[dict] = mapped_column(JSONB)  # e.g. {"agent_tag": "high_stakes"}
    target_model_key: Mapped[str] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Runs (thin — Langfuse owns deep tracing; LangGraph owns checkpoint state)
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = _uuid_pk()  # doubles as the LangGraph thread_id
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued | running | paused_hitl | completed | failed
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONB)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(255))
    requested_by: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    approvals: Mapped[list["RunApproval"]] = relationship(back_populates="run")


class RunApproval(Base):
    __tablename__ = "run_approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    tool_call_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    requested_at: Mapped[datetime] = _created_at()
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped["Run"] = relationship(back_populates="approvals")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class IngestionSource(Base):
    __tablename__ = "ingestion_sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(20))  # file | sql_db | datalake
    name: Mapped[str] = mapped_column(String(255), unique=True)
    connection_config: Mapped[dict] = mapped_column(JSONB, default=dict)  # secret refs only
    embedding_model_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = _created_at()

    runs: Mapped[list["IngestionRun"]] = relationship(back_populates="source")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_sources.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="running")
    rows_processed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    source: Mapped["IngestionSource"] = relationship(back_populates="runs")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_sources.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(String(255))
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# RBAC / governance
# ---------------------------------------------------------------------------


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)  # admin | operator | agent_caller
    created_at: Mapped[datetime] = _created_at()

    role_permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "runs:create", "tools:register"

    role_permissions: Mapped[list["RolePermission"]] = relationship(back_populates="permission")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped["Role"] = relationship(back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="role_permissions")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hashed_key: Mapped[str] = mapped_column(String(255), unique=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    principal_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(255))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class PiiFinding(Base):
    __tablename__ = "pii_findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reference: Mapped[str] = mapped_column(String(255))  # tool_call ref or ingestion ref
    entity_type: Mapped[str] = mapped_column(String(100))  # e.g. EMAIL_ADDRESS, US_SSN
    action_taken: Mapped[str] = mapped_column(String(20))  # masked | blocked
    created_at: Mapped[datetime] = _created_at()


__all__ = [
    "Base",
    "Agent",
    "AgentTool",
    "ToolSource",
    "Tool",
    "ToolCredential",
    "ModelProvider",
    "ModelRegistryEntry",
    "ModelRoutingRule",
    "Run",
    "RunApproval",
    "IngestionSource",
    "IngestionRun",
    "Embedding",
    "Role",
    "Permission",
    "RolePermission",
    "ApiKey",
    "AuditLog",
    "PiiFinding",
    "UniqueConstraint",
]
