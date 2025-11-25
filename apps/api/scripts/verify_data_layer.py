import asyncio
import json
import uuid
from datetime import datetime
from app.core.kafka import kafka_service
from app.core.taskiq import broker
from app.services.pipeline.tasks import fetch_context


async def verify_flow():
    print("Starting verification...")

    # 1. Start services
    await kafka_service.start()
    await broker.startup()

    # 2. Simulate Kafka Message
    session_id = str(uuid.uuid4())
    message = {
        "user_id": "test_user_123",
        "session_id": session_id,
        "text": "Hello, this is a test message.",
        "timestamp": datetime.utcnow().isoformat(),
        "metadata": {"source": "verification_script"},
    }

    print(f"Sending message to Kafka: {message}")
    await kafka_service.send_message("voice.input", message)

    # 3. Wait a bit for consumer to pick it up (consumer is running in main app,
    # but here we are just testing the producer and taskiq dispatch manually if we wanted)
    # Since we can't easily run the full app and this script together in this environment
    # without background processes, we will verify the TaskIQ part directly.

    print("Dispatching TaskIQ task directly...")
    task = await fetch_context.kiq(
        user_id="test_user_123",
        session_id=session_id,
        text="Hello from direct task dispatch",
    )
    print(f"Task dispatched: {task.task_id}")

    # 4. Cleanup
    await broker.shutdown()
    await kafka_service.stop()
    print("Verification complete.")


if __name__ == "__main__":
    asyncio.run(verify_flow())
