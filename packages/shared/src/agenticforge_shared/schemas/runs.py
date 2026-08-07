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
    # M5: explicit model_key to use instead of the agent's registry-resolved
    # default (routing rules still apply if this is omitted). Must match an
    # existing model_registry.model_key — checked at resolution time in the
    # worker, not validated here (that would need a DB round-trip in the
    # request path for a check that already happens where it matters).
    model_override: str | None = None


class RunCreateResponse(BaseModel):
    run_id: uuid.UUID


class RunResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    input: dict
    output: dict | None = None
    model_override: str | None = None
    langfuse_trace_id: str | None = None

    model_config = {"from_attributes": True}
