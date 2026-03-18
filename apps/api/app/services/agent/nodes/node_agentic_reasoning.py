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
from app.services.agent.evals.conversation_context import ConversationContext
from app.services.agent.core.bus import Message
from app.services.agent.nodes.node_reasoning import ReasoningNode
from app.services.integrations.tool_payload import build_tools_payload
from app.services.parser import command_parser
from app.services.parser.intent_to_tool import map_intent_to_tool_call
from app.workers.helpers.redis_events import try_cached_spotify_play
from app.services.pipeline.helpers.function_calls import extract_response_function_calls
from app.services.pipeline.routers.router import pipeline_router
from app.services.pipeline.services.gemini_service import get_gemini_service
from app.core.redis import get_redis_client
from app.workers.helpers.redis_events import append_history, get_history

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
        logger.info(
            "AgentReasoningNode initialized with Redis History tracking",
            extra={"node_id": self.id, "max_context_length": max_context_length},
        )

    async def _append_to_redis(self, redis: Any, user_id: str, event: Any) -> None:
        if isinstance(event, UserTranscriptionReceived):
            await append_history(redis, user_id, "user", event.content, history_limit=self.max_context_length)
        elif isinstance(event, AgentResponse):
            await append_history(redis, user_id, "assistant", event.content, history_limit=self.max_context_length)
        elif isinstance(event, ToolResult):
            summary = event.result_str or event.error or ""
            if summary:
                resp = f"Tool result for {event.tool_name}: {summary}"
                await append_history(redis, user_id, "assistant", resp, history_limit=self.max_context_length)

    async def generate(
        self, message: Message
    ) -> AsyncGenerator[Union[AgentResponse, ToolCall, ToolResult], None]:
        user_id = self._extract_user_id(message)
        if not user_id:
            logger.warning("Missing user_id on incoming message")
            return

        logger.debug("Processing message", extra={"user_id": user_id})
        redis = await get_redis_client()
        await self._append_to_redis(redis, user_id, message.event)

        conversation_messages = await get_history(redis, user_id)
        
        context = ConversationContext(
            events=[message.event],
            system_prompt=self.system_prompt,
            metadata={"user_id": user_id, "conversation_messages": conversation_messages}
        )

        async for chunk in self.process_context(context):
            await self._append_to_redis(redis, user_id, chunk)
            yield chunk

    async def process_context(
        self, context: ConversationContext
    ) -> AsyncGenerator[EventInstance, None]:
        user_id = str(context.metadata.get("user_id", ""))
        conversation_messages = context.metadata.get("conversation_messages", [])
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

            if should_fast_path_parse and not intent.requires_clarification:
                tool_call = map_intent_to_tool_call(intent)
                if tool_call:
                    tool_name, tool_args = tool_call
                    
                    if tool_name == "spotify.play":
                        redis = await get_redis_client()
                        cached_result = await try_cached_spotify_play(
                            redis, user_id, tool_args, history_limit=self.max_context_length
                        )
                        if cached_result:
                            logger.info("Used cached Spotify fast-path result", extra={"user_id": user_id})
                            yield cached_result
                            return

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
