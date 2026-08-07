import os
import uuid

from agenticforge_shared.db.models import Agent, Run
from agenticforge_shared.db.session import get_session
from agenticforge_shared.schemas.runs import (
    MESSAGE_INPUT_KEYS,
    RunCreateRequest,
    RunCreateResponse,
    RunResponse,
    extract_message,
)
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
_redis_pool = None


async def _get_redis_pool():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _redis_pool


@router.post("", response_model=RunCreateResponse)
async def create_run(body: RunCreateRequest) -> RunCreateResponse:
    if extract_message(body.input) is None:
        raise HTTPException(
            status_code=422,
            detail=f"input must contain one of {MESSAGE_INPUT_KEYS!r}",
        )

    async with get_session() as session:
        result = await session.execute(select(Agent).where(Agent.name == body.agent_name))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail=f"no such agent: {body.agent_name}")

        run = Run(
            agent_id=agent.id,
            status="queued",
            input=body.input,
            model_override=body.model_override,
            requested_by="api",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    pool = await _get_redis_pool()
    await pool.enqueue_job("run_graph", str(run_id))

    return RunCreateResponse(run_id=run_id)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: uuid.UUID) -> RunResponse:
    async with get_session() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return RunResponse.model_validate(run)
