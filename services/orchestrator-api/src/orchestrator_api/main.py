from fastapi import FastAPI

from orchestrator_api.api.v1 import runs

app = FastAPI(title="AgenticForge Orchestrator API", version="0.1.0")
app.include_router(runs.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
