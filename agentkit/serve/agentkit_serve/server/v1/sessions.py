"""Session lifecycle HTTP routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentkit.infra.events.store import InMemoryEventStore
from agentkit_serve.server.database import get_db
from agentkit.runtime.sessions.manager import SessionManager
from agentkit_serve.server.deps import get_current_supabase_user
from agentkit_serve.server.session_store import PostgresSessionStore

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    user: dict = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """List active sessions for the authenticated user."""
    manager = SessionManager(
        InMemoryEventStore(), session_store=PostgresSessionStore(db)
    )
    sessions = await manager.list_active(user["id"])
    return {"sessions": sessions}
