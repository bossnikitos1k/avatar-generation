import os

from celery import Celery

# Use single Redis URL for broker/backend as requested.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("avatar_generator", broker=REDIS_URL, backend=REDIS_URL)

# Configure serializers and task time limits.
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_time_limit=600,
    task_soft_time_limit=540,
)

# Auto-discover tasks from app.tasks module.
celery_app.autodiscover_tasks(["app.tasks"])

