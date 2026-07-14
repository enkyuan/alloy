"""Shared JWT utilities used by serve HTTP deps and WebSocket auth paths."""

from __future__ import annotations

from typing import Any

from kaji_serve.config import settings


def decode_bearer_token(token: str) -> dict[str, Any]:
    """Decode a Supabase JWT and return the payload with 'id' set to 'sub'.

    Uses python-jose for local HS256 decode, with no network call to the
    Supabase auth API.

    Raises:
        HTTPException 401: if the token is invalid, expired, or missing a sub.
        HTTPException 503: if JWT trust settings are incomplete.
    """
    try:
        from fastapi import HTTPException, status  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "fastapi is required for HTTPException. "
            "Install it in the host package (kaji-serve already depends on it)."
        ) from exc

    secret = settings.JWT_SECRET.strip()
    issuer = settings.JWT_ISSUER.strip()
    audience = settings.JWT_AUDIENCE.strip()
    if not secret or not issuer or not audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )

    try:
        from jose import JWTError, jwt  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "python-jose is required for JWT decoding. "
            "Install it in the host package (kaji-serve already depends on it)."
        ) from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require_iss": True, "require_aud": True},
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
