"""Shared JWT utilities used by both HTTP deps and WebSocket auth paths."""

from __future__ import annotations

from typing import Any

from agentkit.core.config import settings


def decode_bearer_token(token: str) -> dict[str, Any]:
    """Decode a Supabase JWT and return the payload with 'id' set to 'sub'.

    Uses python-jose (available in agentkit-serve) for local HS256 decode —
    no network call to the Supabase auth API.

    Both dependencies (python-jose and fastapi) are lazily imported so that the
    SDK itself remains installable without them; they are guaranteed to be present
    in the agentkit-serve runtime that calls this function.

    Raises:
        HTTPException 401: if the token is invalid, expired, or missing a sub.
    """
    try:
        from jose import JWTError, jwt  # noqa: PLC0415 — lazy; python-jose lives in serve
    except ImportError as exc:
        raise RuntimeError(
            "python-jose is required for JWT decoding. "
            "Install it in the host package (agentkit-serve already depends on it)."
        ) from exc

    try:
        from fastapi import HTTPException, status  # noqa: PLC0415 — lazy; fastapi lives in serve
    except ImportError as exc:
        raise RuntimeError(
            "fastapi is required for HTTPException. "
            "Install it in the host package (agentkit-serve already depends on it)."
        ) from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from error

    payload = {**payload, "id": payload.get("sub")}

    if not payload.get("id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return payload
