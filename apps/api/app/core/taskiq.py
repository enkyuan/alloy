from typing import Optional

from taskiq import TaskiqEvents
from taskiq_aio_pika import AioPikaBroker
from taskiq_redis import RedisAsyncResultBackend

from app.core.config import settings

# Configure Result Backend
result_backend = RedisAsyncResultBackend(
    redis_url=settings.REDIS_URL,
)

# Configure Broker
broker = AioPikaBroker(
    url=settings.RABBITMQ_URL,
    result_backend=result_backend,
)


# Startup/Shutdown events
@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state):
    print("TaskIQ Worker started")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state):
    print("TaskIQ Worker stopped")
