"""
Taskiq configuration for background job processing.
"""


from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from app.core.config import settings

# Define the broker
# We instantiate it directly so the Taskiq CLI can import 'broker'
broker = ListQueueBroker(
    url=settings.REDIS_URL,
    queue_name="default",
).with_result_backend(
    RedisAsyncResultBackend(redis_url=settings.REDIS_URL)
)

def get_broker() -> ListQueueBroker:
    """Get the global broker instance."""
    return broker


# Define queues
QUEUE_HIGH_PRIORITY = "queue:high_priority"
QUEUE_BACKGROUND = "queue:background"
