from fastapi import FastAPI

app = FastAPI(title="AgenticForge Orchestrator API", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
