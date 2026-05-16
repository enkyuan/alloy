import asyncio
import logging
import uuid

from sdk.agents.voice_worker.node_agentic_reasoning import AgentReasoningNode
from sdk.agents.prompts import ASSISTANT_SYSTEM_INSTRUCTION
from sdk.events.voice_models import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from sdk.agents.voice_bus import Bridge, Bus, Message
from sdk.workflows.queue import RedisPublisher, RedisStreamInput
from sdk.workers.helpers.redis_constants import (
    TOOL_RESULT_DLQ_DEAD_KEY,
    TOOL_RESULT_DLQ_KEY,
    TOOL_RESULT_DLQ_MAX_DRAIN,
    TOOL_RESULT_DLQ_MAX_RETRIES,
    VOICE_INPUT_DLQ_DEAD_KEY,
    VOICE_INPUT_DLQ_KEY,
    VOICE_INPUT_DLQ_MAX_DRAIN,
    VOICE_INPUT_DLQ_MAX_RETRIES,
)
from sdk.workers.tasks.tools import execute_tool_call

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


async def _publish_tool_result(message: Message, publisher: RedisPublisher) -> None:
    event = message.event
    if not isinstance(event, ToolResult):
        return
    if not event.user_id:
        logger.warning("ToolResult missing user_id; skipping publish")
        return
    logger.debug(
        "Publishing tool result",
        extra={"user_id": event.user_id, "tool_name": event.tool_name},
    )
    await publisher.publish(event.user_id, event, event_type="tool.result")


async def run() -> None:
    logger.info("Starting bus worker")
    bus = Bus()
    publisher = RedisPublisher()

    reasoning_node = AgentReasoningNode(
        system_prompt=ASSISTANT_SYSTEM_INSTRUCTION,
        node_id="agent",
    )
    logger.info("Initialized reasoning node", extra={"node_id": reasoning_node.id})

    stream_bridge = Bridge("redis_stream")
    tool_result_bridge = Bridge("redis_tool_results")

    reasoning_bridge = Bridge(reasoning_node)
    reasoning_bridge.on(UserTranscriptionReceived).stream(
        reasoning_node.generate
    ).broadcast()
    # Only route externally produced tool results back into reasoning.
    # ToolResults emitted by this reasoning node already complete in-process.
    reasoning_bridge.on(
        ToolResult,
        source=tool_result_bridge.node_id,
        metadata=lambda value: (
            isinstance(value, dict)
            and value.get("source") == "taskiq.execute_tool_call"
        ),
    ).stream(reasoning_node.generate).broadcast()

    output_bridge = Bridge("redis_output")

    async def publish_response(message: Message) -> None:
        await _publish_agent_response(message, publisher)

    async def publish_error(message: Message) -> None:
        await _publish_agent_error(message, publisher)

    async def publish_tool_result(message: Message) -> None:
        await _publish_tool_result(message, publisher)

    async def dispatch_tool(message: Message) -> None:
        await _dispatch_tool_call(message, publisher)

    output_bridge.on(AgentResponse).map(publish_response)
    output_bridge.on(AgentError).map(publish_error)
    # Publish ToolResults only when they originate from this reasoning node.
    # This prevents redis_tool_results -> publish -> stream feedback loops.
    output_bridge.on(ToolResult, source=reasoning_node.id).map(publish_tool_result)
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

    # Run the DLQ-enabled stream consumers in the background
    import socket

    from sdk.core.redis import RedisKeys

    host_id = socket.gethostname()

    voice_input_stream = RedisStreamInput(
        stream=RedisKeys.STREAM_VOICE_INPUT,
        group=RedisKeys.GROUP_LLM_WORKER,
        consumer=f"llm_voice_worker_{host_id}",
    )

    tool_result_stream = RedisStreamInput(
        stream=RedisKeys.STREAM_TOOL_RESULTS,
        group=RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
        consumer=f"llm_tool_results_worker_{host_id}",
    )

    _background_tasks = [
        asyncio.create_task(
            voice_input_stream.consume_to_bus(
                "redis_stream",
                bus,
                VOICE_INPUT_DLQ_KEY,
                VOICE_INPUT_DLQ_DEAD_KEY,
                VOICE_INPUT_DLQ_MAX_DRAIN,
                VOICE_INPUT_DLQ_MAX_RETRIES,
                2000,
                24 * 3600,
                7 * 24 * 3600,
                dlq_coerce_fields=False,
            )
        ),
        asyncio.create_task(
            tool_result_stream.consume_to_bus(
                "redis_tool_results",
                bus,
                TOOL_RESULT_DLQ_KEY,
                TOOL_RESULT_DLQ_DEAD_KEY,
                TOOL_RESULT_DLQ_MAX_DRAIN,
                TOOL_RESULT_DLQ_MAX_RETRIES,
                2000,
                24 * 3600,
                7 * 24 * 3600,
                dlq_coerce_fields=False,
            )
        ),
    ]

    await bus.shutdown_event.wait()
    for task in _background_tasks:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(run())
