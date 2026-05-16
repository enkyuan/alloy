"""Voice modality facade — STT streaming and Soniox integration."""

from src.modalities.voice.gateway import (
    connect_soniox as ConnectSoniox,
    listen_to_soniox as ListenToSoniox,
)
from src.modalities.voice.soniox import soniox_service as SonioxService
from src.modalities.voice.stt import (
    TranscriptionSessionState,
    authenticate_ws as AuthenticateWebSocket,
    process_client_messages as ProcessClientMessages,
    safe_send_json as SafeSendJson,
    send_error_message as SendErrorMessage,
    stream_agent_updates as StreamAgentUpdates,
)

__all__ = [
    "AuthenticateWebSocket",
    "ConnectSoniox",
    "ListenToSoniox",
    "ProcessClientMessages",
    "SafeSendJson",
    "SendErrorMessage",
    "SonioxService",
    "StreamAgentUpdates",
    "TranscriptionSessionState",
]
