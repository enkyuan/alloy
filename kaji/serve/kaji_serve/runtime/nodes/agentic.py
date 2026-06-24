"""Agentic reasoning node with scatter-gather tool execution."""

import asyncio
import contextlib
import logging
import uuid
from typing import (
    Any,
    AsyncContextManager,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

from kaji_serve.runtime.nodes.reasoning import ReasoningNode
from kaji.core.config import get_settings
from kaji.modalities.voice.event_models import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from kaji.modalities.voice.event_registry import EventInstance
from kaji.runtime.agents.history import HistoryStore, InMemoryHistoryStore
from kaji.runtime.providers.registry import get_provider
from kaji_serve.runtime.nodes.conversation_context import ConversationContext
from kaji_serve.runtime.messaging.bus import Message
from kaji.runtime.tools.payload import build_tools_payload
from kaji.runtime.tools.registry import execute_tool
from kaji.runtime.tools.retriever import get_tool_retriever

logger = logging.getLogger(__name__)

# Maximum number of LLM↔tool round-trips before we force a text response.
# Prevents runaway loops if the model keeps requesting tools indefinitely.
MAX_TOOL_ITERATIONS = 5

# A session factory yields a (possibly ``None``) DB session for tool execution.
# Server/worker callers inject one backed by ``AsyncSessionLocal``; the default
# yields ``None`` so embedded use needs no database.
SessionFactory = Callable[[], AsyncContextManager[Any]]


@contextlib.asynccontextmanager
async def _null_session_factory() -> AsyncGenerator[None, None]:
    """Default session factory: yields ``None`` (no database)."""
    yield None


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
        session_factory: Optional[SessionFactory] = None,
        history_store: Optional[HistoryStore] = None,
    ):
        super().__init__(
            system_prompt=system_prompt,
            max_context_length=max_context_length,
            node_id=node_id,
        )
        # Injected so tool execution stays database-free by default. Callers that
        # need persistence (server/workers) pass a factory yielding a real session.
        self._session_factory: SessionFactory = session_factory or _null_session_factory
        # Conversation history backend. In-memory by default (no infra); the
        # reference service injects a Redis-backed store for durable history.
        self._history: HistoryStore = history_store or InMemoryHistoryStore()
        logger.info(
            "AgentReasoningNode initialized",
            extra={"node_id": self.id, "max_context_length": max_context_length},
        )

    # ------------------------------------------------------------------
    # Conversation history helpers
    # ------------------------------------------------------------------

    async def _append_to_history(self, user_id: str, event: Any) -> None:
        """Persist an event into the conversation history store."""
        if isinstance(event, UserTranscriptionReceived):
            await self._history.append(
                user_id,
                "user",
                event.content,
                history_limit=self.max_context_length,
            )
        elif isinstance(event, AgentResponse):
            await self._history.append(
                user_id,
                "assistant",
                event.content,
                history_limit=self.max_context_length,
            )
        elif isinstance(event, ToolResult):
            summary = _tool_result_summary(event)
            if summary:
                await self._history.append(
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
            async with self._session_factory() as db:
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

        await self._append_to_history(user_id, message.event)

        conversation_messages = await self._history.get(user_id)

        context = ConversationContext(
            events=[message.event],
            system_prompt=self.system_prompt,
            metadata={
                "user_id": user_id,
                "conversation_messages": conversation_messages,
            },
        )

        async for chunk in self.process_context(context):
            await self._append_to_history(user_id, chunk)
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
                # Neutral tool payload (flat list); the provider translates it
                # to its own function-calling format at its boundary.
                tools_list = build_tools_payload(allowed_names=top_tools)

                provider = get_provider(get_settings().KAJI_MODEL_PROVIDER)
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
                *(self._execute_single_tool(fc, user_id) for fc in function_calls)
            )

            # Splice results into conversation and history.
            for result in results:
                # Surface raw tool results to downstream clients so they can
                # execute client-side actions (e.g. Spotify app playback).
                yield result
                await self._append_to_history(user_id, result)
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
