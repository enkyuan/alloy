"""STT subpackage — handler logic plus provider implementations.

Public surface re-exports the names previously available at
`agentkit.voice.stt` (when it was a single module) so existing callers keep
working unchanged.
"""

from agentkit.voice.stt.handler import (
    TranscriptionSessionState,
    authenticate_ws,
    cancel_pending_publish,
    compose_final_text,
    extract_websocket_bearer_token,
    forward_agent_updates,
    forward_audio_chunk,
    handle_command_message,
    handle_end_signal,
    normalize_command_text,
    process_client_messages,
    publish_transcription,
    safe_send_json,
    schedule_pending_transcription_publish,
    send_error_message,
    stream_agent_updates,
)

__all__ = [
    "TranscriptionSessionState",
    "authenticate_ws",
    "cancel_pending_publish",
    "compose_final_text",
    "extract_websocket_bearer_token",
    "forward_agent_updates",
    "forward_audio_chunk",
    "handle_command_message",
    "handle_end_signal",
    "normalize_command_text",
    "process_client_messages",
    "publish_transcription",
    "safe_send_json",
    "schedule_pending_transcription_publish",
    "send_error_message",
    "stream_agent_updates",
]
