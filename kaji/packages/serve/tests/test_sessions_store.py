from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kaji.runtime.sessions.store import SessionRecord
from kaji_serve.server.session_store import PostgresSessionStore
from kaji_serve.server.v1.sessions import list_sessions


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


@pytest.mark.asyncio
async def test_postgres_session_store_lists_conversations_as_session_records():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_Result(
                [
                    SimpleNamespace(
                        id="sess-1",
                        user_id="user-1",
                        title="Support",
                        created_at=now,
                    )
                ]
            )
        )
    )

    records = await PostgresSessionStore(db).list_sessions("user-1")

    assert records == [
        SessionRecord(
            session_id="sess-1",
            user_id="user-1",
            title="Support",
            created_at=now.timestamp(),
        )
    ]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_sessions_route_uses_db_backed_store():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_Result(
                [
                    SimpleNamespace(
                        id="sess-1",
                        user_id="user-1",
                        title=None,
                        created_at=now,
                    )
                ]
            )
        )
    )

    response = await list_sessions(user={"id": "user-1"}, db=db)

    assert response == {
        "sessions": [
            {
                "session_id": "sess-1",
                "user_id": "user-1",
                "created_at": now.timestamp(),
                "title": "",
            }
        ]
    }
