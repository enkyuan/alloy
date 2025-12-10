import logging
import asyncio
import time
from app.core.event_backbone import event_backbone
from app.services.pipeline.tasks import fetch_context

logger = logging.getLogger(__name__)


async def process_event(message_id: str, message: dict):
    """Process event from Redis Stream."""
    logger.info(f"Processing event {message_id}: {message}")

    try:
        user_id = message.get("user_id")
        text = message.get("text")

        # We might not have session_id in the simple stream entry described in the diagram
        # but the code used it. Let's assume user_id is enough or generate one.
        session_id = message.get("session_id", f"sess_{int(time.time())}")

        if user_id and text:
            logger.info(f"Triggering TaskIQ pipeline for user {user_id}")
            task = await fetch_context.kiq(
                user_id=user_id, session_id=session_id, text=text
            )
            logger.info(f"Task dispatched: {task.task_id}")

    except Exception as e:
        logger.error(f"Error processing event {message_id}: {e}")


async def start_stream_consumer():
    """Start consuming from stream:voice_input."""
    if not event_backbone.redis:
        await event_backbone.connect()

    stream_key = "stream:voice_input"
    group_name = "llm_service"
    consumer_name = (
        "api_worker_1"  # In a real deployment, this should be unique per instance
    )

    # Create consumer group if not exists
    try:
        await event_backbone.redis.xgroup_create(
            stream_key, group_name, id="0", mkstream=True
        )
    except Exception as e:
        # Ignore if group already exists
        if "BUSYGROUP" not in str(e):
            logger.warning(f"Error creating consumer group: {e}")

    logger.info(f"Started consumer for {stream_key} group {group_name}")

    while True:
        try:
            # Read new messages
            streams = await event_backbone.redis.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_key: ">"},
                count=1,
                block=5000,
            )

            if streams:
                for stream, messages in streams:
                    for message_id, message in messages:
                        await process_event(message_id, message)
                        # Acknowledge
                        await event_backbone.redis.xack(
                            stream_key, group_name, message_id
                        )

        except asyncio.CancelledError:
            logger.info("Stream consumer cancelled")
            break
        except Exception as e:
            logger.error(f"Error in stream consumer: {e}")
            await asyncio.sleep(5)
