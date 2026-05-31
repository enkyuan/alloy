import asyncio
import logging
import uuid

from agentkit.runtime.agents.nodes.agentic import AgentReasoningNode
from agentkit.runtime.agents.prompts import ASSISTANT_SYSTEM_INSTRUCTION
from agentkit.modalities.voice.event_models import (
    AgentAudioChunk,
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from agentkit.runtime.agents.messaging import Bridge, Bus, Message
from agentkit.runtime.workflows.queue import RedisPublisher, RedisStreamInput
from agentkit.core.config import get_settings
from agentkit.core.database import get_sessionmaker
from agentkit.core.redis import RedisConfig, RedisKeys
from agentkit.modalities.voice.tts import (
    TTSNotConfiguredError,
    TTSProvider,
    VoiceTTSAdapter,
    get_tts_provider,
)
from agentkit.workers.tasks.tools import execute_tool_call

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


async def _synthesize_and_publish(
    message: Message, publisher: RedisPublisher, tts: "TTSProvider"
) -> None:
    """Synthesize an AgentResponse to speech and publish AgentAudioChunk events.

    Streams audio from the configured TTS provider and forwards each chunk
    (base64, seq-ordered) on the user-updates channel. Failures are logged and
    swallowed so a TTS outage never blocks the text response.
    """
    event = message.event
    if not isinstance(event, AgentResponse):
        return
    if not event.user_id or not (event.content or "").strip():
        return
    try:
        seq = 0
        async for chunk in tts.stream(event.content):
            if not chunk:
                continue
            await publisher.publish(
                event.user_id,
                AgentAudioChunk.from_bytes(chunk, seq=seq, user_id=event.user_id),
                event_type="agent.audio",
            )
            seq += 1
    except TTSNotConfiguredError:
        # Provider not configured at runtime; text response already went out.
        pass
    except Exception as error:
        logger.error(
            "TTS synthesis failed; sent text only",
            extra={"user_id": event.user_id, "error": str(error)},
            exc_info=True,
        )


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
        # Worker runs with full infra: back tool execution with real DB sessions.
        session_factory=lambda: get_sessionmaker()(),
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

    # Wire TTS only when a provider is configured. The factory returns the
    # no-op VoiceTTSAdapter for TTS_PROVIDER=none, so text-only deployments
    # skip synthesis entirely (and never build a provider client).
    tts_provider: TTSProvider = get_tts_provider()
    if not isinstance(tts_provider, VoiceTTSAdapter):
        async def synthesize_audio(message: Message) -> None:
            await _synthesize_and_publish(message, publisher, tts_provider)

        output_bridge.on(AgentResponse).map(synthesize_audio)
        logger.info(
            "TTS enabled for agent responses",
            extra={"provider": get_settings().TTS_PROVIDER},
        )

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

    from agentkit.core.redis import RedisKeys

    host_id = socket.gethostname()

    agent_input_stream = RedisStreamInput(
        stream=RedisKeys.STREAM_AGENT_INPUT,
        group=RedisKeys.GROUP_LLM_WORKER,
        consumer=f"{RedisKeys.CONSUMER_LLM_WORKER}_{host_id}",
    )

    tool_result_stream = RedisStreamInput(
        stream=RedisKeys.STREAM_TOOL_RESULTS,
        group=RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
        consumer=f"{RedisKeys.CONSUMER_TOOL_RESULTS_WORKER}_{host_id}",
    )

    _background_tasks = [
        asyncio.create_task(
            agent_input_stream.consume_to_bus(
                "redis_stream",
                bus,
                RedisKeys.VOICE_INPUT_DLQ_KEY,
                RedisKeys.VOICE_INPUT_DLQ_DEAD_KEY,
                RedisConfig.VOICE_INPUT_DLQ_MAX_DRAIN,
                RedisConfig.VOICE_INPUT_DLQ_MAX_RETRIES,
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
                RedisKeys.TOOL_RESULT_DLQ_KEY,
                RedisKeys.TOOL_RESULT_DLQ_DEAD_KEY,
                RedisConfig.TOOL_RESULT_DLQ_MAX_DRAIN,
                RedisConfig.TOOL_RESULT_DLQ_MAX_RETRIES,
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
