"""Session lifecycle HTTP routes."""

from fastapi import APIRouter, Depends

from src.api.deps import get_current_supabase_user
from src.events.store import InMemoryEventStore
from src.sessions.manager import SessionManager

router = APIRouter(prefix="/sessions", tags=["sessions"])
_session_manager = SessionManager(InMemoryEventStore())


@router.get("")
async def list_sessions(user: dict = Depends(get_current_supabase_user)):
    """List active sessions for the authenticated user."""
    sessions = await _session_manager.list_active(user["id"])
    return {"sessions": sessions}
