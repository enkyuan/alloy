"""STT subpackage — handler logic plus provider implementations."""

from kaji_serve.modalities.voice.stt.handler import (
    TranscriptionSessionState,
    authenticate_ws,
    compose_final_text,
    extract_websocket_access_token,
    forward_audio_chunk,
    handle_end_signal,
    process_client_messages,
    safe_send_json,
    send_error_message,
)

__all__ = [
    "TranscriptionSessionState",
    "authenticate_ws",
    "compose_final_text",
    "extract_websocket_access_token",
    "forward_audio_chunk",
    "handle_end_signal",
    "process_client_messages",
    "safe_send_json",
    "send_error_message",
]
