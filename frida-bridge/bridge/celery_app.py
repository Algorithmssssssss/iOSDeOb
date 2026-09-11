import os

from celery import Celery

celery_app = Celery(
    "frida_bridge",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(
    task_default_queue="frida",
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_hijack_root_logger=False,
)

from . import tasks  # noqa: E402,F401
