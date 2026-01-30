import json
from typing import Any, Callable, Dict, List, Optional, cast

Response = Any
ResponseFunctionToolCall = object
ResponseOutputMessage = object
ResponseOutputRefusal = object
ResponseOutputText = object

from app.services.agent.events import (
    AgentResponse,
    EventInstance,
    EventType,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)


def convert_messages_to_openai(
    events: List[EventInstance],
    handlers: Optional[
        Dict[EventType, Callable[[EventInstance], Dict[str, Any]]]
    ] = None,
) -> List[Dict[str, Any]]:
    """Convert conversation messages to OpenAI format.

    With OpenAI, all messages need to be in the context.

    Args:
        events: List of events.
        handlers: Dictionary of event type to handler function.
            The handler function should return a dictionary of OpenAI-formatted messages.

    Returns:
        List of messages in OpenAI format
    """
    handlers = handlers or {}

    openai_messages = []
    for event in events:
        event_type = type(event)
        if event_type in handlers:
            openai_messages.append(handlers[event_type](event))
            continue

        if isinstance(event, AgentResponse):
            openai_messages.append({"role": "assistant", "content": event.content})
        elif isinstance(event, UserTranscriptionReceived):
            openai_messages.append({"role": "user", "content": event.content})
        elif isinstance(event, ToolCall):
            if event.raw_response:
                openai_messages.append(event.raw_response)
        elif isinstance(event, ToolResult):
            if event.tool_call_id:
                openai_messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": event.tool_call_id,
                        "output": event.result_str,
                    }
                )

    return openai_messages


def extract_text_from_response(response: Response) -> str:
    """Extract all text content from OpenAI response output.

    Args:
        response: OpenAI response object

    Returns:
        Combined text content from the response
    """
    text_content = ""
    response_any = cast(Any, response)
    for msg in response_any.output:
        msg_any = cast(Any, msg)
        if hasattr(msg_any, "content"):
            for content in msg_any.content:
                content_any = cast(Any, content)
                if hasattr(content_any, "text"):
                    text_content += content_any.text
                elif hasattr(content_any, "refusal"):
                    text_content += content_any.refusal
    return text_content


def extract_tool_calls_from_response(response: Response) -> List[ToolCall]:
    """Extract function tool calls from OpenAI response output.

    Args:
        response: OpenAI response object

    Returns:
        List of tool calls with name and arguments
    """
    tool_calls = []
    response_any = cast(Any, response)
    for msg in response_any.output:
        msg_any = cast(Any, msg)
        if hasattr(msg_any, "name") and hasattr(msg_any, "arguments"):
            tool_calls.append(
                ToolCall(
                    tool_name=msg_any.name,
                    tool_args=json.loads(msg_any.arguments),
                    tool_call_id=str(getattr(msg_any, "id", "")),
                    raw_response=getattr(msg_any, "model_dump", lambda: {})(),
                )
            )
    return tool_calls


def has_tool_calls(response: Response) -> bool:
    """Check if response contains any tool calls.

    Args:
        response: OpenAI response object

    Returns:
        True if response contains tool calls, False otherwise
    """
    response_any = cast(Any, response)
    for msg in response_any.output:
        msg_any = cast(Any, msg)
        if hasattr(msg_any, "name") and hasattr(msg_any, "arguments"):
            return True
    return False
