import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://agenticforge:agenticforge@localhost:5432/agenticforge"
)


def _psycopg_dsn() -> str:
    # AsyncPostgresSaver uses psycopg (v3) under the hood, not the asyncpg
    # driver the rest of the app uses via SQLAlchemy — needs a plain
    # postgresql:// DSN, not the SQLAlchemy dialect-prefixed one.
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def get_checkpointer():
    async with AsyncPostgresSaver.from_conn_string(_psycopg_dsn()) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
