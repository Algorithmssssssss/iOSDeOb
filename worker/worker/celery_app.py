import os

from celery import Celery

celery_app = Celery(
    "worker",
    broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
)
celery_app.conf.update(
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_hijack_root_logger=False,
)

# Ensure tasks module is registered with this app
from . import tasks  # noqa: E402,F401
