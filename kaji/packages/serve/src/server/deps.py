"""FastAPI dependencies shared across v1 routes."""

from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kaji_serve.server.auth_utils import decode_bearer_token

security = HTTPBearer()


async def get_current_supabase_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """Validate Bearer auth and return Supabase user payload."""
    return decode_bearer_token(credentials.credentials)
