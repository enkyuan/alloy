import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.core.events import (
    AgentError,
    AgentResponse,
    EventInstance,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.services.agent.core.bus import Message
from app.services.agent.evals.conversation_context import ConversationContext
from app.services.agent.nodes.node_reasoning import ReasoningNode
from app.services.integrations.tool_payload import build_tools_payload
from app.services.parser import command_parser
from app.services.parser.intent_to_tool import map_intent_to_tool_call
from app.services.pipeline.helpers.function_calls import extract_response_function_calls
from app.services.pipeline.routers.router import pipeline_router
from app.services.pipeline.services.gemini_service import get_gemini_service

logger = logging.getLogger(__name__)

_MAX_TRACKED_USERS = 1000
_INACTIVE_USER_TTL_SECONDS = 60 * 60


class AgentReasoningNode(ReasoningNode):
    """Reasoning node that wraps the agent LLM/tooling pipeline."""

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
        self._events_by_user: OrderedDict[str, List[Any]] = OrderedDict()
        self._last_seen_by_user: dict[str, float] = {}
        logger.info(
            "AgentReasoningNode initialized",
            extra={"node_id": self.id, "max_context_length": max_context_length},
        )

    async def generate(
        self, message: Message
    ) -> AsyncGenerator[Union[AgentResponse, ToolCall, ToolResult], None]:
        user_id = self._extract_user_id(message)
        if not user_id:
            logger.warning("Missing user_id on incoming message")
            return

        logger.debug("Processing message", extra={"user_id": user_id})
        self._add_event_for_user(user_id, message.event)

        conversation_context = self._build_conversation_context(user_id)
        async for chunk in self.process_context(conversation_context):
            self._add_event_for_user(user_id, chunk)
            yield chunk

    async def process_context(
        self, context: ConversationContext
    ) -> AsyncGenerator[EventInstance, None]:
        user_id = str(context.metadata.get("user_id", ""))
        if not user_id:
            return

        last_event = context.events[-1] if context.events else None
        if isinstance(last_event, UserTranscriptionReceived):
            route_decision = pipeline_router.decide(last_event.content)
            logger.debug(
                "Pipeline router decision",
                extra={
                    "user_id": user_id,
                    "should_parse_as_command": route_decision.should_parse_as_command,
                    "reason": route_decision.reason,
                },
            )

            logger.debug(
                "Parsing intent from latest user message", extra={"user_id": user_id}
            )
            intent = command_parser.parse_command(
                last_event.content,
                alternatives=last_event.alternatives,
            )
            parser_command_like = bool(intent.parser_meta.get("command_like", False))
            should_fast_path_parse = (
                route_decision.should_parse_as_command or parser_command_like
            )
            logger.debug(
                "Parser decision",
                extra={
                    "user_id": user_id,
                    "intent": intent.intent,
                    "confidence": round(intent.confidence, 4),
                    "parser_command_like": parser_command_like,
                    "should_fast_path_parse": should_fast_path_parse,
                },
            )

            if should_fast_path_parse and not intent.requires_clarification:
                tool_call = map_intent_to_tool_call(intent)
                if tool_call:
                    tool_name, tool_args = tool_call
                    logger.info(
                        "Routing via parser intent",
                        extra={"user_id": user_id, "intent": intent.intent},
                    )
                    yield ToolCall(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=str(uuid.uuid4()),
                        user_id=user_id,
                    )
                    return

        conversation_messages = _build_conversation_messages(context.events)
        if not conversation_messages:
            logger.debug("No messages to process", extra={"user_id": user_id})
            return

        try:
            logger.debug("Requesting Gemini response", extra={"user_id": user_id})
            response = await get_gemini_service().generate_chat_response(
                messages=conversation_messages,
                system_instruction=self.system_prompt,
                tools=build_tools_payload(),
            )
        except Exception:
            logger.error("Gemini failure", exc_info=True, extra={"user_id": user_id})
            yield AgentError(error="Gemini request failed.", user_id=user_id)
            return

        response_function_calls = extract_response_function_calls(response)
        if response_function_calls:
            logger.info(
                "Gemini requested tool calls",
                extra={"user_id": user_id, "count": len(response_function_calls)},
            )
            for function_call in response_function_calls:
                tool_args = dict(function_call.args or {})
                yield ToolCall(
                    tool_name=function_call.name,
                    tool_args=tool_args,
                    tool_call_id=str(uuid.uuid4()),
                    user_id=user_id,
                )
            return

        response_text = response.text or ""
        if not response_text:
            response_text = "Sorry, I couldn't generate a response right now."

        logger.debug("Generated agent response", extra={"user_id": user_id})
        yield AgentResponse(content=response_text, user_id=user_id)

    def _extract_user_id(self, message: Message) -> Optional[str]:
        event = message.event
        if hasattr(event, "user_id") and getattr(event, "user_id"):
            return str(getattr(event, "user_id"))
        return None

    def _touch_user(self, user_id: str) -> None:
        self._last_seen_by_user[user_id] = time.monotonic()
        if user_id in self._events_by_user:
            self._events_by_user.move_to_end(user_id)

    def _prune_user_state(self) -> None:
        now = time.monotonic()
        expired = [
            user_id
            for user_id, seen_at in self._last_seen_by_user.items()
            if now - seen_at > _INACTIVE_USER_TTL_SECONDS
        ]
        for user_id in expired:
            self._events_by_user.pop(user_id, None)
            self._last_seen_by_user.pop(user_id, None)

        while len(self._events_by_user) > _MAX_TRACKED_USERS:
            oldest_user_id, _ = self._events_by_user.popitem(last=False)
            self._last_seen_by_user.pop(oldest_user_id, None)

    def _add_event_for_user(self, user_id: str, event: Any) -> None:
        self._prune_user_state()
        events = self._events_by_user.setdefault(user_id, [])
        self._touch_user(user_id)

        previous_events = self.conversation_events
        self.conversation_events = events
        try:
            # Reuse base class merge logic for transcript/assistant chunks.
            self.add_event(event)
            if len(self.conversation_events) > self.max_context_length:
                self.conversation_events = self.conversation_events[-self.max_context_length :]
            self._events_by_user[user_id] = self.conversation_events
        finally:
            self.conversation_events = previous_events

    def _build_conversation_context(
        self, user_id: Optional[str] = None
    ) -> ConversationContext:
        self._prune_user_state()
        user_id = user_id or ""
        self._touch_user(user_id)
        events = self._events_by_user.get(user_id, [])

        previous_events = self.conversation_events
        self.conversation_events = events
        try:
            context = super()._build_conversation_context(user_id=user_id)
        finally:
            self.conversation_events = previous_events

        context.metadata["user_id"] = user_id
        return context


def _build_conversation_messages(events: List[Any]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    for event in events:
        if isinstance(event, UserTranscriptionReceived):
            messages.append({"role": "user", "content": event.content})
        elif isinstance(event, AgentResponse):
            messages.append({"role": "assistant", "content": event.content})
        elif isinstance(event, ToolResult):
            summary = event.result_str or event.error or ""
            if summary:
                messages.append(
                    {
                        "role": "assistant",
                        "content": f"Tool result for {event.tool_name}: {summary}",
                    }
                )
    return messages
