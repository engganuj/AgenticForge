import uuid

from pydantic import BaseModel


class RunCreateRequest(BaseModel):
    agent_name: str
    input: dict


class RunCreateResponse(BaseModel):
    run_id: uuid.UUID


class RunResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    input: dict
    output: dict | None = None
    langfuse_trace_id: str | None = None

    model_config = {"from_attributes": True}
