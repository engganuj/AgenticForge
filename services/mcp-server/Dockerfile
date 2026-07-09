FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY packages/shared /app/packages/shared
COPY services/mcp-server /app/services/mcp-server

RUN uv pip install --system --no-cache /app/packages/shared /app/services/mcp-server

EXPOSE 8100

CMD ["python", "-m", "mcp_server.server"]
