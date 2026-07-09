FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY packages/shared /app/packages/shared
COPY services/orchestrator-api /app/services/orchestrator-api

RUN uv pip install --system --no-cache /app/packages/shared /app/services/orchestrator-api

EXPOSE 8000

CMD ["uvicorn", "orchestrator_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
