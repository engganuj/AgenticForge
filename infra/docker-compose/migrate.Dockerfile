FROM python:3.11-slim

RUN pip install --no-cache-dir alembic psycopg2-binary sqlalchemy pgvector

WORKDIR /app

COPY packages/shared /app/packages/shared
COPY migrations /app/migrations

RUN pip install --no-cache-dir /app/packages/shared

ENTRYPOINT []
