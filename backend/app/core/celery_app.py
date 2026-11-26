from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

from backend.app.core.config import settings


celery_app = Celery(
    "ragnex",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Task modules a worker must import to register tasks. (autodiscover_tasks only looks for
# a `tasks` submodule, i.e. backend.app.tasks.tasks, which doesn't exist, so a worker
# started with `-A backend.app.core.celery_app.celery_app` registered nothing.)
celery_app.conf.include = [
    "backend.app.tasks.parsing",
    "backend.app.tasks.embedding",
    "backend.app.tasks.indexing",
    "backend.app.tasks.purge",
]

# Queues
default_exchange = Exchange("ragnex", type="direct")
celery_app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default", queue_arguments={"x-max-priority": 10}),
    Queue("parsing", default_exchange, routing_key="parsing", queue_arguments={"x-max-priority": 10}),
    Queue("embedding", default_exchange, routing_key="embedding", queue_arguments={"x-max-priority": 10}),
    Queue("indexing", default_exchange, routing_key="indexing", queue_arguments={"x-max-priority": 10}),
)

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "ragnex"
celery_app.conf.task_default_exchange_type = "direct"
celery_app.conf.task_default_routing_key = "default"

# Priority support (RabbitMQ/Redis supports priority with queue arguments above)
celery_app.conf.task_default_priority = 5
celery_app.conf.task_queue_max_priority = 10

# Result tracking / serialization
celery_app.conf.task_ignore_result = False
celery_app.conf.result_extended = True
celery_app.conf.task_track_started = True
celery_app.conf.accept_content = ["json"]
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"

# Testing / local dev toggles
celery_app.conf.task_always_eager = settings.celery_task_always_eager
celery_app.conf.task_eager_propagates = settings.celery_task_eager_propagates

# Route tasks by name prefix
celery_app.conf.task_routes = {
    "backend.app.tasks.parsing.*": {"queue": "parsing", "routing_key": "parsing"},
    "backend.app.tasks.embedding.*": {"queue": "embedding", "routing_key": "embedding"},
    "backend.app.tasks.indexing.*": {"queue": "indexing", "routing_key": "indexing"},
}
