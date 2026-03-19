"""Token encryption migration helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.db_session import db_close, db_commit, db_execute, db_rollback
from app.core.crypto import ENCRYPTED_SECRET_PREFIX, encrypt_secret, is_encrypted_secret
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def migrate_plaintext_integration_tokens() -> int:
    """Encrypt legacy plaintext integration tokens stored in the database."""
    migrated_rows = 0
    db = AsyncSessionLocal()
    try:
        result = await db_execute(
            db,
            text(
                """
                SELECT id, access_token, refresh_token
                FROM integrations
                WHERE (access_token IS NOT NULL AND access_token NOT LIKE :encrypted_prefix)
                   OR (refresh_token IS NOT NULL AND refresh_token NOT LIKE :encrypted_prefix)
                """
            ),
            {"encrypted_prefix": f"{ENCRYPTED_SECRET_PREFIX}%"},
        )
        rows = result.mappings().all()

        now = datetime.now(timezone.utc)
        for row in rows:
            row_id = row.get("id")
            access_token = row.get("access_token")
            refresh_token = row.get("refresh_token")
            if not row_id:
                continue

            updates: dict[str, Any] = {"id": row_id, "updated_at": now}
            assignments: list[str] = []

            if (
                isinstance(access_token, str)
                and access_token
                and not is_encrypted_secret(access_token)
            ):
                updates["access_token"] = encrypt_secret(access_token)
                assignments.append("access_token = :access_token")

            if (
                isinstance(refresh_token, str)
                and refresh_token
                and not is_encrypted_secret(refresh_token)
            ):
                updates["refresh_token"] = encrypt_secret(refresh_token)
                assignments.append("refresh_token = :refresh_token")

            if not assignments:
                continue

            assignments.append("updated_at = :updated_at")
            # Safe dynamic SQL note:
            # `assignments` contains only hardcoded column fragments from above.
            await db_execute(
                db,
                text(
                    f"""
                    UPDATE integrations
                    SET {", ".join(assignments)}
                    WHERE id = :id
                    """
                ),
                updates,
            )
            migrated_rows += 1

        if migrated_rows:
            await db_commit(db)
            logger.warning(
                "Migrated plaintext integration tokens",
                extra={"count": migrated_rows},
            )
        else:
            await db_rollback(db)

        return migrated_rows
    except Exception as error:
        try:
            await db_rollback(db)
        except Exception:
            logger.debug("Rollback failed after token migration error", exc_info=True)

        if "greenlet library is required" in str(error).lower():
            logger.warning(
                "Skipping plaintext integration token migration because greenlet is unavailable"
            )
            return 0

        logger.error("Failed to migrate plaintext integration tokens", exc_info=True)
        return 0
    finally:
        try:
            await db_close(db)
        except Exception:
            logger.debug("Failed to close token migration session", exc_info=True)
