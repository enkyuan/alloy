"""Agentic reasoning node with scatter-gather tool execution."""

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.core.database import AsyncSessionLocal
from app.core.events import (
    AgentError,
    AgentResponse,
    EventInstance,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.core.redis import get_redis_client
from app.services.agent.core.bus import Message
from app.services.agent.evals.conversation_context import ConversationContext
from app.services.agent.nodes.node_reasoning import ReasoningNode
from app.services.integrations.dispatcher import execute_tool
from app.services.integrations.tool_payload import build_tools_payload
from app.services.integrations.tool_retriever import get_tool_retriever
from app.services.pipeline.helpers.function_calls import extract_response_function_calls
from app.services.pipeline.services.gemini_service import get_gemini_service
from app.workers.helpers.redis_events import (
    append_history,
    get_history,
    try_cached_spotify_play,
)

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
            await append_history(redis, user_id, "user", event.content, history_limit=self.max_context_length)
        elif isinstance(event, AgentResponse):
            await append_history(redis, user_id, "assistant", event.content, history_limit=self.max_context_length)
        elif isinstance(event, ToolResult):
            summary = _tool_result_summary(event)
            if summary:
                await append_history(redis, user_id, "assistant", summary, history_limit=self.max_context_length)

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
        tool_name: str = call.name
        tool_args: Dict[str, Any] = dict(call.args or {})
        call_id = str(uuid.uuid4())

        # Spotify fast-path: return cached playback if available.
        if tool_name == "spotify.play":
            cached = await try_cached_spotify_play(
                redis, user_id, tool_args, history_limit=self.max_context_length,
            )
            if cached:
                return ToolResult(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    result={"status": "Playing from cache"},
                    user_id=user_id,
                    tool_call_id=call_id,
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
        conversation_messages: List[Dict[str, str]] = context.metadata.get("conversation_messages", [])
        redis: Any = context.metadata.get("redis") or await get_redis_client()
        last_event = context.events[-1] if context.events else None

        # RAG-based tool retrieval: only on fresh user input.
        if isinstance(last_event, UserTranscriptionReceived):
            top_tools = await get_tool_retriever().get_top_tools(
                last_event.content, top_k=3, threshold=0.6,
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
                response = await get_gemini_service().generate_chat_response(
                    messages=conversation_messages,
                    system_instruction=self.system_prompt,
                    tools=dynamic_tools,
                )
            except Exception:
                logger.error("Gemini failure", exc_info=True, extra={"user_id": user_id})
                yield AgentError(error="Gemini request failed.", user_id=user_id)
                return

            # ---- Plain text response → done ------------------------------
            function_calls = extract_response_function_calls(response)
            if not function_calls:
                text = response.text or "Sorry, I couldn't generate a response right now."
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
                *(self._execute_single_tool(fc, redis, user_id) for fc in function_calls)
            )

            # Splice results into conversation and Redis history.
            for result in results:
                # Surface raw tool results to downstream clients so they can
                # execute client-side actions (e.g. Spotify app playback).
                yield result
                await self._append_to_redis(redis, user_id, result)
                conversation_messages.append({
                    "role": "assistant",
                    "content": _tool_result_summary(result),
                })

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
