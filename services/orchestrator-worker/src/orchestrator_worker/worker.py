import os

from arq.connections import RedisSettings

from orchestrator_worker.tasks import run_graph

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


class WorkerSettings:
    functions = [run_graph]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
