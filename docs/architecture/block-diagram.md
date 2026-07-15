# Project Block Diagram

This diagram shows the high-level architecture for AgenticForge, including the current Phase 1 services and the future extensions planned in the repository.

```mermaid
flowchart LR
    User[User / Client] --> API[Orchestrator API]
    API --> Worker[Orchestrator Worker]
    API --> MCP[MCP Server]

    subgraph CoreServices[Core services]
        API
        Worker
        MCP
    end

    subgraph DataLayer[Data and platform services]
        DB[(PostgreSQL + pgvector)]
        Redis[(Redis)]
        LF[Langfuse]
    end

    subgraph Shared[Shared platform components]
        SH[Shared Packages]
        MIG[Database Migrations]
    end

    subgraph Extensions[Planned extensions]
        ING[Ingestion Pipelines]
        SEM[Semantic Layer]
        RBAC[RBAC / Governance]
        MODELS[Model Registry / Routing]
    end

    API --> DB
    Worker --> DB
    API --> Redis
    Worker --> Redis
    API --> LF
    MCP --> LF

    API --> SH
    Worker --> SH
    MCP --> SH

    MIG --> DB

    ING --> DB
    SEM --> DB
    RBAC --> DB
    MODELS --> API
    MODELS --> Worker

    API --> Ext[External model APIs / tools]
    MCP --> Ext
```

## Component summary

- Orchestrator API: FastAPI entry point for orchestration requests and health checks.
- Orchestrator Worker: LangGraph-based execution engine for asynchronous workflow runs.
- MCP Server: Streamable HTTP server exposing tool integrations and adapters.
- Shared Packages: SQLAlchemy models, RBAC helpers, schema definitions, and shared utilities.
- PostgreSQL + Redis + Langfuse: core runtime and observability dependencies.
- Ingestion Pipelines, Semantic Layer, RBAC/Governance, and Model Registry: planned expansion areas.
