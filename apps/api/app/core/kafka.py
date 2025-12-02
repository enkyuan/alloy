import asyncio
import json
import logging
from typing import Any, Dict, Optional, Callable

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from app.core.config import settings

logger = logging.getLogger(__name__)


class KafkaService:
    def __init__(self):
        self.producer: Optional[AIOKafkaProducer] = None
        self.bootstrap_servers = settings.KAFKA_BOOTSTRAP_SERVERS
        self.client_id = settings.KAFKA_CLIENT_ID

    async def start(self):
        """Start the Kafka producer."""
        try:
            logger.info(f"Initializing Kafka producer at {self.bootstrap_servers}")
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id=self.client_id,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self.producer.start()
            logger.info("Kafka producer started successfully")
        except Exception as e:
            logger.error(f"Failed to start Kafka producer: {e}", exc_info=True)

    async def stop(self):
        """Stop the Kafka producer."""
        if self.producer:
            try:
                await self.producer.stop()
                logger.info("Kafka producer stopped")
            except Exception as e:
                logger.error(f"Error stopping Kafka producer: {e}", exc_info=True)

    async def send_message(
        self, topic: str, value: Dict[str, Any], key: Optional[str] = None
    ):
        """Send a message to a Kafka topic."""
        if not self.producer:
            logger.warning("Kafka producer not initialized, skipping message")
            return

        try:
            key_bytes = key.encode("utf-8") if key else None
            logger.debug(f"Sending message to topic {topic} (key={key})")
            await self.producer.send_and_wait(topic, value=value, key=key_bytes)
            logger.info(f"Sent message to topic {topic}")
        except Exception as e:
            logger.error(
                f"Failed to send message to Kafka topic {topic}: {e}", exc_info=True
            )

    async def consume_messages(
        self, topic: str, callback: Callable[[Dict[str, Any]], Any]
    ):
        """Consume messages from a topic and call the callback."""
        logger.info(f"Starting consumer for topic {topic}")
        try:
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                group_id="modal-group",
                value_deserializer=lambda x: json.loads(x.decode("utf-8")),
            )
            await consumer.start()
            logger.info(f"Consumer started for topic {topic}")
            try:
                async for msg in consumer:
                    logger.debug(f"Received message from {topic}: {msg.value}")
                    try:
                        await callback(msg.value)
                    except Exception as e:
                        logger.error(
                            f"Error processing message from {topic}: {e}", exc_info=True
                        )
            finally:
                await consumer.stop()
                logger.info(f"Consumer stopped for topic {topic}")
        except Exception as e:
            logger.error(
                f"Failed to start consumer for topic {topic}: {e}", exc_info=True
            )


kafka_service = KafkaService()
