"""Shared helpers for Redis realtime modules."""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import msgpack


def coerce_str_payload(payload: Any) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        return str(payload)


def encode_msgpack_base64(payload: Any) -> str:
    packed = cast(bytes, msgpack.packb(payload, use_bin_type=True))
    return base64.b64encode(packed).decode("ascii")


def decode_msgpack_base64(payload_b64: str) -> Any:
    packed = base64.b64decode(payload_b64.encode("ascii"), validate=True)
    return msgpack.unpackb(packed, raw=False, strict_map_key=False)


async def append_to_list_with_ttl(
    redis: Any,
    *,
    key: str,
    payload: Any,
    maxlen: int,
    ttl_seconds: int,
) -> None:
    await redis.lpush(key, payload)
    if maxlen > 0:
        await redis.ltrim(key, 0, maxlen - 1)
    if ttl_seconds > 0:
        await redis.expire(key, ttl_seconds)
