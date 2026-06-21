"""Versioned event envelope helpers for Redis transport."""

from __future__ import annotations

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
    payload: Union[BaseModel, Dict[str, Any]],
) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return payload
    return payload


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
    payload: Union[BaseModel, Dict[str, Any]],
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


def parse_event_envelope(raw: Union[Dict[str, Any], bytes, bytearray]) -> EventEnvelope:
    """Validate and parse an incoming event envelope."""

    def _unpack(raw_bytes: bytes) -> Dict[str, Any]:
        unpacked = msgpack.unpackb(raw_bytes, raw=False, strict_map_key=False)
        if not isinstance(unpacked, dict):
            raise ValueError("Invalid msgpack event payload")
        return unpacked

    if isinstance(raw, (bytes, bytearray)):
        candidate = _unpack(bytes(raw))
    else:
        msgpack_payload = None
        for key, value in raw.items():
            if key == "_msgpack" or key == b"_msgpack":
                msgpack_payload = value
                break

        if isinstance(msgpack_payload, (bytes, bytearray, memoryview)):
            candidate = _unpack(bytes(msgpack_payload))
        else:
            candidate = dict(raw)

    # Decode byte keys defensively for pydantic validation.
    candidate = {
        key.decode("utf-8") if isinstance(key, bytes) else key: value
        for key, value in candidate.items()
    }

    candidate.setdefault("version", EVENT_SCHEMA_VERSION)
    envelope = EventEnvelope.model_validate(candidate)
    if isinstance(envelope.payload, str):
        raise ValueError("String event payloads are no longer supported")
    if not is_supported_event_version(envelope.version):
        raise ValueError(f"Unsupported event envelope version: {envelope.version}")
    return envelope


def to_redis_stream_fields(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an event envelope into Redis stream-safe binary fields."""
    return {"_msgpack": msgpack.packb(envelope, use_bin_type=True)}
