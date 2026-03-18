"""Versioned event envelope helpers for Redis transport."""

from __future__ import annotations

import json
import msgpack
from typing import Any, Dict, Optional, Union, cast

from pydantic import BaseModel, Field

EVENT_SCHEMA_VERSION = "1.0"


class EventEnvelope(BaseModel):
    """Versioned event envelope used for Redis stream/pubsub transport."""

    version: str = EVENT_SCHEMA_VERSION
    type: str
    user_id: Optional[str] = None
    payload: Any
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _coerce_payload(
    payload: Union[BaseModel, Dict[str, Any], str],
) -> Union[str, Dict[str, Any]]:
    if isinstance(payload, BaseModel):
        return payload.model_dump_json()
    if isinstance(payload, dict):
        return payload
    return str(payload)


def is_supported_event_version(version: str) -> bool:
    """Return whether an envelope version is supported by this runtime."""
    return (
        str(version).split(".", maxsplit=1)[0]
        == EVENT_SCHEMA_VERSION.split(".", maxsplit=1)[0]
    )


def build_event_envelope(
    *,
    event_type: str,
    user_id: Optional[str],
    payload: Union[BaseModel, Dict[str, Any], str],
    metadata: Optional[Dict[str, Any]] = None,
    version: str = EVENT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Build a validated versioned event envelope."""
    envelope = EventEnvelope(
        version=version,
        type=event_type,
        user_id=user_id,
        payload=_coerce_payload(payload),
        metadata=cast(Any, metadata or {}),
    )
    return envelope.model_dump()


def parse_event_envelope(raw: Dict[str, Any]) -> EventEnvelope:
    """Validate and parse an incoming event envelope."""
    # Fast path: MsgPack binary decoding
    msgpack_payload = None
    for k, v in raw.items():
        if k == "_msgpack" or k == b"_msgpack":
            msgpack_payload = v
            break
    if msgpack_payload and isinstance(msgpack_payload, bytes):
        candidate = msgpack.unpackb(msgpack_payload, strict_map_key=False)
        if isinstance(candidate, dict):
            # Decode string keys defensively 
            candidate = {k.decode("utf-8") if isinstance(k, bytes) else k: v for k, v in candidate.items()}
    else:
        # Legacy fast-path JSON decoding
        candidate = dict(raw)
        metadata = candidate.get("metadata")
        if isinstance(metadata, str):
            try:
                decoded_metadata = json.loads(metadata)
                if isinstance(decoded_metadata, dict):
                    candidate["metadata"] = decoded_metadata
            except json.JSONDecodeError:
                candidate["metadata"] = {}

        # Safely decode byte-keys passed down locally
        candidate = {k.decode("utf-8") if isinstance(k, bytes) else k: v for k, v in candidate.items()}

    candidate.setdefault("version", EVENT_SCHEMA_VERSION)
    envelope = EventEnvelope.model_validate(candidate)
    if not is_supported_event_version(envelope.version):
        raise ValueError(f"Unsupported event envelope version: {envelope.version}")
    return envelope


def to_redis_stream_fields(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an event envelope into Redis stream-safe binary fields."""
    return {"_msgpack": msgpack.packb(envelope)}
