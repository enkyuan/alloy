"""Agentic reasoning node with scatter-gather tool execution."""

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from src.agents.voice_worker.node_reasoning import ReasoningNode
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.events.voice_models import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from src.events.voice_registry import EventInstance
from src.core.redis import get_redis_client
from src.providers.registry import get_provider
from src.agents.voice_worker.conversation_context import ConversationContext
from src.agents.voice_bus.bus import Message
from src.tools.payload import build_tools_payload
from src.tools.registry import execute_tool
from src.tools.retriever import get_tool_retriever
from src.workers.helpers.redis_events import append_history, get_history

logger = logging.getLogger(__name__)

# Maximum number of LLM↔tool round-trips before we force a text response.
# Prevents runaway loops if the model keeps requesting tools indefinitely.
MAX_TOOL_ITERATIONS = 5


def _tool_result_summary(result: ToolResult) -> str:
    """Build a concise, machine-oriented summary for conversation history."""
    tool_label = f"[tool:{result.tool_name}]"
    if result.error:
        return f"{tool_label} error={result.error.strip()}"

    payload = result.result if isinstance(result.result, dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    assert isinstance(data, dict)

    status = payload.get("status")
    if isinstance(status, str) and status.strip():
        return f"{tool_label} status={status.strip()}"

    if data.get("requires_clarification"):
        option_items = data.get("option_items")
        option_count = len(option_items) if isinstance(option_items, list) else 0
        return f"{tool_label} clarification options={option_count}"

    action_required = data.get("action_required")
    if action_required == "client_playback":
        uri = data.get("uri")
        if isinstance(uri, str) and uri.strip():
            return f"{tool_label} client_playback uri={uri.strip()}"
        return f"{tool_label} client_playback"

    return f"{tool_label} done"


class AgentReasoningNode(ReasoningNode):
    """Reasoning node that wraps the agent LLM/tooling pipeline.

    Key architectural properties:
      - **Scatter-gather execution**: when the LLM emits N tool calls in one
        turn, all N are executed concurrently via ``asyncio.gather`` inside
        this node rather than being yielded back to the bus.  This eliminates
        the race where N independent ``ToolResult`` events each re-trigger
        the reasoning bridge in parallel.
      - **Deterministic looping**: after gathering results the node splices
        them back into the conversation history and re-invokes the LLM in
        the *same* generator call, guaranteeing a single coherent response.
    """

    def __init__(
        self,
        system_prompt: str,
        max_context_length: int = 100,
        node_id: Optional[str] = None,
    ):
        super().__init__(
            system_prompt=system_prompt,
            max_context_length=max_context_length,
            node_id=node_id,
        )
        logger.info(
            "AgentReasoningNode initialized",
            extra={"node_id": self.id, "max_context_length": max_context_length},
        )

    # ------------------------------------------------------------------
    # Redis history helpers
    # ------------------------------------------------------------------

    async def _append_to_redis(self, redis: Any, user_id: str, event: Any) -> None:
        """Persist an event into the Redis conversation history."""
        if isinstance(event, UserTranscriptionReceived):
            await append_history(
                redis,
                user_id,
                "user",
                event.content,
                history_limit=self.max_context_length,
            )
        elif isinstance(event, AgentResponse):
            await append_history(
                redis,
                user_id,
                "assistant",
                event.content,
                history_limit=self.max_context_length,
            )
        elif isinstance(event, ToolResult):
            summary = _tool_result_summary(event)
            if summary:
                await append_history(
                    redis,
                    user_id,
                    "assistant",
                    summary,
                    history_limit=self.max_context_length,
                )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_single_tool(
        self,
        call: Any,
        redis: Any,
        user_id: str,
    ) -> ToolResult:
        """Execute one tool call, returning a ``ToolResult`` regardless of outcome."""
        tool_name: str = (
            call.get("name", "")
            if isinstance(call, dict)
            else getattr(call, "name", "")
        )
        tool_args: Dict[str, Any] = (
            call.get("arguments", {})
            if isinstance(call, dict)
            else dict(getattr(call, "args", {}))
        )
        call_id = (
            call.get("id", str(uuid.uuid4()))
            if isinstance(call, dict)
            else str(uuid.uuid4())
        )

        try:
            async with AsyncSessionLocal() as db:
                result_data = await execute_tool(user_id, tool_name, tool_args, db)
            return ToolResult(
                tool_name=tool_name,
                tool_args=tool_args,
                result=result_data,
                user_id=user_id,
                tool_call_id=call_id,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name,
                tool_args=tool_args,
                error=str(exc),
                user_id=user_id,
                tool_call_id=call_id,
            )

    # ------------------------------------------------------------------
    # Entry point (called by the Bridge)
    # ------------------------------------------------------------------

    async def generate(
        self, message: Message
    ) -> AsyncGenerator[Union[AgentResponse, ToolCall, ToolResult], None]:
        user_id = self._extract_user_id(message)
        if not user_id:
            logger.warning("Missing user_id on incoming message")
            return

        redis = await get_redis_client()
        await self._append_to_redis(redis, user_id, message.event)

        conversation_messages = await get_history(redis, user_id)

        context = ConversationContext(
            events=[message.event],
            system_prompt=self.system_prompt,
            metadata={
                "user_id": user_id,
                "conversation_messages": conversation_messages,
                "redis": redis,
            },
        )

        async for chunk in self.process_context(context):
            await self._append_to_redis(redis, user_id, chunk)
            yield chunk

    # ------------------------------------------------------------------
    # Core reasoning loop
    # ------------------------------------------------------------------

    async def process_context(
        self, context: ConversationContext
    ) -> AsyncGenerator[EventInstance, None]:
        user_id: str = str(context.metadata.get("user_id", ""))
        conversation_messages: List[Dict[str, str]] = context.metadata.get(
            "conversation_messages", []
        )
        redis: Any = context.metadata.get("redis") or await get_redis_client()
        last_event = context.events[-1] if context.events else None

        # RAG-based tool retrieval: only on fresh user input.
        if isinstance(last_event, UserTranscriptionReceived):
            top_tools = await get_tool_retriever().get_top_tools(
                last_event.content,
                top_k=3,
                threshold=0.6,
            )
        else:
            top_tools = None

        for iteration in range(MAX_TOOL_ITERATIONS):
            if not conversation_messages:
                logger.debug("No messages to process", extra={"user_id": user_id})
                return

            # ---- LLM call ------------------------------------------------
            try:
                dynamic_tools = (
                    build_tools_payload(allowed_names=top_tools)
                    if top_tools is not None
                    else build_tools_payload()
                )

                # In build_tools_payload, the return structure is [{"function_declarations": [...]}] for Gemini.
                # However, the generic provider expects a flat list of tool schemas for standard abstraction,
                # but we'll let the provider handle it or we adjust dynamic_tools here.
                # Since dynamic_tools is currently returning [{"function_declarations": ...}], we'll extract it.
                tools_list = []
                if dynamic_tools and "function_declarations" in dynamic_tools[0]:
                    tools_list = dynamic_tools[0]["function_declarations"]

                provider = get_provider(settings.AGENTKIT_MODEL_PROVIDER)
                response = await provider.generate(
                    messages=conversation_messages,
                    system_instruction=self.system_prompt,
                    tools=tools_list,
                )
            except Exception:
                logger.error(
                    "LLM provider failure", exc_info=True, extra={"user_id": user_id}
                )
                yield AgentError(error="LLM request failed.", user_id=user_id)
                return

            # ---- Plain text response → done ------------------------------
            function_calls = response.tool_calls
            if not function_calls:
                text = (
                    response.text or "Sorry, I couldn't generate a response right now."
                )
                logger.debug("Generated agent response", extra={"user_id": user_id})
                yield AgentResponse(content=text, user_id=user_id)
                return

            # ---- Scatter-gather tool execution ---------------------------
            logger.info(
                "Scatter-gathering %s tool calls (iteration %s/%s)",
                len(function_calls),
                iteration + 1,
                MAX_TOOL_ITERATIONS,
                extra={"user_id": user_id},
            )

            results: list[ToolResult] = await asyncio.gather(
                *(
                    self._execute_single_tool(fc, redis, user_id)
                    for fc in function_calls
                )
            )

            # Splice results into conversation and Redis history.
            for result in results:
                # Surface raw tool results to downstream clients so they can
                # execute client-side actions (e.g. Spotify app playback).
                yield result
                await self._append_to_redis(redis, user_id, result)
                conversation_messages.append(
                    {
                        "role": "assistant",
                        "content": _tool_result_summary(result),
                    }
                )

            # Loop back to let the LLM synthesize a final answer.

        # Exhausted all iterations — force a graceful exit.
        logger.warning(
            "Hit MAX_TOOL_ITERATIONS (%s); forcing text response",
            MAX_TOOL_ITERATIONS,
            extra={"user_id": user_id},
        )
        yield AgentResponse(
            content="I've completed the requested actions.",
            user_id=user_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_user_id(self, message: Message) -> Optional[str]:
        event = message.event
        if hasattr(event, "user_id") and getattr(event, "user_id"):
            return str(getattr(event, "user_id"))
        return None
