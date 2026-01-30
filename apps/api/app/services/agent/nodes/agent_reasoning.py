import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.core.events import (
    AgentError,
    AgentResponse,
    EventInstance,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.services.agent.bus import Message
from app.services.agent.nodes.conversation_context import ConversationContext
from app.services.agent.nodes.reasoning import ReasoningNode
from app.services.integrations import list_tool_specs
from app.services.pipeline.cmd_parser import command_parser
from app.services.pipeline.gemini import get_gemini_service

logger = logging.getLogger(__name__)


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
        self._events_by_user: Dict[str, List[Any]] = {}
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

        ctx = self._build_conversation_context(user_id)
        async for chunk in self.process_context(ctx):
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
            logger.debug(
                "Parsing intent from latest user message", extra={"user_id": user_id}
            )
            intent = command_parser.parse_command(last_event.content)
            if intent and not intent.requires_clarification:
                tool_call = _intent_to_tool_call(intent, user_id)
                if tool_call:
                    logger.info(
                        "Routing via parser intent",
                        extra={"user_id": user_id, "intent": intent.intent},
                    )
                    yield tool_call
                    return

        messages = _events_to_messages(context.events)
        if not messages:
            logger.debug("No messages to process", extra={"user_id": user_id})
            return

        try:
            logger.debug("Requesting Gemini response", extra={"user_id": user_id})
            response = await get_gemini_service().generate_chat_response(
                messages=messages,
                system_instruction=self.system_prompt,
                tools=_build_tools_payload(),
            )
        except Exception as exc:
            logger.error("Gemini failure", exc_info=True, extra={"user_id": user_id})
            yield AgentError(error="Gemini request failed.", user_id=user_id)
            return

        function_calls = _extract_function_calls(response)
        if function_calls:
            logger.info(
                "Gemini requested tool calls",
                extra={"user_id": user_id, "count": len(function_calls)},
            )
            for call in function_calls:
                yield ToolCall(
                    tool_name=call["name"],
                    tool_args=call.get("args", {}),
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

    def _add_event_for_user(self, user_id: str, event: Any) -> None:
        events = self._events_by_user.setdefault(user_id, [])
        _append_event(events, event)

    def _build_conversation_context(
        self, user_id: Optional[str] = None
    ) -> ConversationContext:
        user_id = user_id or ""
        events = self._events_by_user.get(user_id, [])
        if len(events) > self.max_context_length:
            events = events[-self.max_context_length :]
            self._events_by_user[user_id] = events

        return ConversationContext(
            events=events,
            system_prompt=self.system_prompt,
            metadata={
                "user_id": user_id,
                "max_context_length": self.max_context_length,
                "total_messages": len(events),
            },
        )


def _append_event(events: List[Any], event: Any) -> None:
    if isinstance(event, Message):
        event = event.event

    if not events:
        events.append(event)
        return

    mergeable = (AgentResponse, UserTranscriptionReceived)
    if isinstance(event, mergeable) and isinstance(events[-1], type(event)):
        events[-1] = type(event)(content=events[-1].content + event.content)
        return

    events.append(event)


def _events_to_messages(events: List[Any]) -> List[Dict[str, str]]:
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


def _build_tools_payload() -> List[Dict[str, Any]]:
    declarations = []
    for spec in list_tool_specs():
        declarations.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )
    return [{"function_declarations": declarations}] if declarations else []


def _extract_function_calls(response: Any) -> List[Dict[str, Any]]:
    function_calls: List[Dict[str, Any]] = []
    if hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        if (
            hasattr(candidate, "content")
            and candidate.content
            and hasattr(candidate.content, "parts")
            and candidate.content.parts
        ):
            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(
                        {
                            "name": part.function_call.name,
                            "args": part.function_call.args or {},
                        }
                    )
    return function_calls


def _intent_to_tool_call(intent, user_id: str) -> Optional[ToolCall]:
    params = intent.parameters or {}

    if intent.intent == "play_track":
        track = params.get("track")
        if not track:
            return None
        artist = params.get("artist")
        query = track
        tool_args: Dict[str, Any] = {"query": query}
        if artist:
            tool_args["artist"] = artist
            tool_args["query"] = f"{track} by {artist}"
        return ToolCall(
            tool_name="spotify.play",
            tool_args=tool_args,
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "play_album":
        album = params.get("album")
        if not album:
            return None
        tool_args = {"album": album}
        if params.get("artist"):
            tool_args["artist"] = params["artist"]
        return ToolCall(
            tool_name="spotify.play_album",
            tool_args=tool_args,
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "play_playlist":
        playlist = params.get("playlist")
        if not playlist:
            return None
        return ToolCall(
            tool_name="spotify.play_playlist",
            tool_args={"playlist": playlist},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "pause":
        return ToolCall(
            tool_name="spotify.pause",
            tool_args={},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "resume":
        return ToolCall(
            tool_name="spotify.resume",
            tool_args={},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "next":
        return ToolCall(
            tool_name="spotify.next",
            tool_args={},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "previous":
        return ToolCall(
            tool_name="spotify.previous",
            tool_args={},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "set_volume":
        level = params.get("level")
        if level is None:
            return None
        return ToolCall(
            tool_name="spotify.set_volume",
            tool_args={"level": level},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "list_devices":
        return ToolCall(
            tool_name="spotify.list_devices",
            tool_args={},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    if intent.intent == "switch_device":
        device = params.get("device")
        if not device:
            return None
        return ToolCall(
            tool_name="spotify.switch_device",
            tool_args={"device_name": device},
            tool_call_id=str(uuid.uuid4()),
            user_id=user_id,
        )

    return None
