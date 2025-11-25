import logging
import asyncio
from app.core.kafka import kafka_service
from app.services.pipeline.tasks import fetch_context, process_llm, route_task

logger = logging.getLogger(__name__)


async def process_voice_input(message: dict):
    """Process voice input messages from Kafka."""
    logger.info(f"Received voice input: {message}")

    try:
        user_id = message.get("user_id")
        session_id = message.get("session_id")
        text = message.get("text")

        if user_id and text:
            logger.info(f"Triggering TaskIQ pipeline for session {session_id}")

            # Trigger the first task in the pipeline
            # We use .kiq() to send the task to the broker
            task = await fetch_context.kiq(
                user_id=user_id, session_id=session_id, text=text
            )

            # In a real pipeline, we might want to chain these using taskiq's chaining capabilities
            # or have fetch_context trigger process_llm upon completion.
            # For now, we just fire and forget the entry point.
            logger.info(f"Task dispatched: {task.task_id}")

    except Exception as e:
        logger.error(f"Error processing voice input: {e}")


async def start_voice_input_consumer():
    """Start the consumer for voice.input topic."""
    logger.info("Starting voice.input consumer...")
    # We use a loop to keep retrying if connection fails or to keep consuming
    while True:
        try:
            await kafka_service.consume_messages("voice.input", process_voice_input)
        except Exception as e:
            logger.error(f"Error in voice.input consumer: {e}")
            await asyncio.sleep(5)
