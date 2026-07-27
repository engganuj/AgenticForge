"""Langfuse tracing setup, shared by orchestrator-worker (and later,
ingestion). Wraps the langfuse SDK's LangChain-compatible CallbackHandler so
call sites don't each read env vars / guess the constructor shape.

If your installed `langfuse` package version's CallbackHandler constructor
differs from what's used here (SDK versions have moved args around across
2.x), check `python -c "from langfuse.callback import CallbackHandler; help(CallbackHandler)"`
and adjust get_langfuse_callback_handler() accordingly.
"""

import os

from langfuse.callback import CallbackHandler


def get_langfuse_callback_handler(*, trace_id: str | None = None) -> CallbackHandler:
    """trace_id, if given, forces the trace to use that ID (we pass the
    orchestrator's own `run_id` so Run.langfuse_trace_id round-trips to a
    real, directly-linkable Langfuse trace instead of an unrelated one).
    """
    return CallbackHandler(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000"),
        trace_id=trace_id,
    )
