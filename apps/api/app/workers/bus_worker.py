import asyncio
import logging
import uuid

from app.core.events import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.services.agent.adapters.redis_io import (
    RedisPublisher,
    RedisPubSubInput,
    RedisStreamInput,
)
from app.services.agent.bridge import Bridge
from app.services.agent.bus import Bus, Message
from app.services.agent.nodes.agent_reasoning import AgentReasoningNode
from app.services.pipeline.tasks import execute_tool_call

SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. "
    "Use tools to control integrations when needed. "
    "If a tool result is provided, respond succinctly to the user."
)

logger = logging.getLogger(__name__)


async def _dispatch_tool_call(message: Message, publisher: RedisPublisher) -> None:
    event = message.event
    if not isinstance(event, ToolCall):
        return

    user_id = event.user_id
    if not user_id:
        logger.warning("ToolCall missing user_id; skipping dispatch")
        return

    tool_call_id = event.tool_call_id or str(uuid.uuid4())
    event.tool_call_id = tool_call_id

    logger.info(
        "Dispatching tool call",
        extra={
            "tool": event.tool_name,
            "user_id": user_id,
            "tool_call_id": tool_call_id,
        },
    )

    await execute_tool_call.kiq(
        user_id=user_id,
        tool_name=event.tool_name,
        tool_args=event.tool_args or {},
        tool_call_id=tool_call_id,
    )

    await publisher.publish(user_id, event, event_type="tool.call")


async def _publish_agent_response(message: Message, publisher: RedisPublisher) -> None:
    event = message.event
    if not isinstance(event, AgentResponse):
        return
    if not event.user_id:
        logger.warning("AgentResponse missing user_id; skipping publish")
        return
    logger.debug("Publishing agent response", extra={"user_id": event.user_id})
    await publisher.publish(event.user_id, event, event_type="agent.response")


async def _publish_agent_error(message: Message, publisher: RedisPublisher) -> None:
    event = message.event
    if not isinstance(event, AgentError):
        return
    if not event.user_id:
        logger.warning("AgentError missing user_id; skipping publish")
        return
    logger.warning(
        "Publishing agent error",
        extra={"user_id": event.user_id, "code": event.code},
    )
    await publisher.publish(event.user_id, event, event_type="agent.error")


async def run() -> None:
    logger.info("Starting bus worker")
    bus = Bus()
    publisher = RedisPublisher()

    stream_input = RedisStreamInput()
    tool_result_input = RedisPubSubInput(allowed_types={"tool.result"})

    reasoning_node = AgentReasoningNode(
        system_prompt=SYSTEM_INSTRUCTION, node_id="agent"
    )
    logger.info("Initialized reasoning node", extra={"node_id": reasoning_node.id})

    stream_bridge = Bridge("redis_stream").with_input_routing(stream_input)
    tool_result_bridge = Bridge("redis_tool_results").with_input_routing(
        tool_result_input
    )

    reasoning_bridge = Bridge(reasoning_node)
    reasoning_bridge.on(UserTranscriptionReceived).stream(
        reasoning_node.generate
    ).broadcast()
    reasoning_bridge.on(ToolResult).stream(reasoning_node.generate).broadcast()

    output_bridge = Bridge("redis_output")

    async def publish_response(message: Message) -> None:
        await _publish_agent_response(message, publisher)

    async def publish_error(message: Message) -> None:
        await _publish_agent_error(message, publisher)

    async def dispatch_tool(message: Message) -> None:
        await _dispatch_tool_call(message, publisher)

    output_bridge.on(AgentResponse).map(publish_response)
    output_bridge.on(AgentError).map(publish_error)
    output_bridge.on(ToolCall).map(dispatch_tool)

    bus.register_bridge("redis_stream", stream_bridge)
    bus.register_bridge("redis_tool_results", tool_result_bridge)
    bus.register_bridge("reasoning", reasoning_bridge)
    bus.register_bridge("redis_output", output_bridge)

    await bus.start()
    logger.info("Bus started")
    await stream_bridge.start()
    logger.info("Stream bridge started")
    await tool_result_bridge.start()
    logger.info("Tool result bridge started")
    await reasoning_bridge.start()
    logger.info("Reasoning bridge started")
    await output_bridge.start()

    logger.info("Agent bus worker running")
    await bus.shutdown_event.wait()


if __name__ == "__main__":
    asyncio.run(run())
