"""Session lifecycle HTTP routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from kaji.runtime.sessions.store import SessionRecord
from kaji_serve.server.database import get_db
from kaji_serve.server.deps import get_current_supabase_user
from kaji_serve.server.session_store import PostgresSessionStore

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_response(record: SessionRecord) -> dict:
    return {
        "session_id": record.session_id,
        "user_id": record.user_id,
        "created_at": record.created_at,
        "title": record.title,
    }


@router.get("")
async def list_sessions(
    user: dict = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """List active sessions for the authenticated user."""
    records = await PostgresSessionStore(db).list_sessions(user["id"])
    sessions = [_session_response(record) for record in records]
    return {"sessions": sessions}
