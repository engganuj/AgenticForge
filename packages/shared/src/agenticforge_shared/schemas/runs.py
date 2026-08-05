import uuid

from pydantic import BaseModel

# Accepted aliases for "the human's message" inside RunCreateRequest.input —
# checked in this order. Kept in one place so the API-side validation (fail
# fast on submit) and the worker (actually reading it) can't drift out of
# sync on which key names are accepted.
MESSAGE_INPUT_KEYS = ("message", "prompt")


def extract_message(input_: dict) -> str | None:
    for key in MESSAGE_INPUT_KEYS:
        if key in input_:
            return input_[key]
    return None


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
