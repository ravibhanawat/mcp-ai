"""
Chat history persistence helpers.

Provides get/save/list/delete operations for conversations and messages.
All DB errors are caught and logged so chat never breaks if DB is unavailable.

Async variants (async_save_message, async_get_or_create_conversation) are
provided for use in FastAPI streaming endpoints so the event loop is never blocked.
"""
import json
import logging
from decimal import Decimal
from datetime import datetime, date
from typing import Any

_logger = logging.getLogger("db.chat_history")


class _SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


def get_or_create_conversation(user_id: str, session_id: str, first_message: str = "") -> int | None:
    """Return conversation_id, creating the row if it doesn't exist yet.

    The title is derived from the first user message (truncated to 80 chars).
    Returns None if the database is unavailable.
    """
    try:
        from db.connection import query_one, get_db
        row = query_one(
            "SELECT id FROM conversations WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
        if row:
            return row["id"]
        title = (first_message[:80] + "…") if len(first_message) > 80 else (first_message or "New conversation")
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (user_id, session_id, title) VALUES (%s, %s, %s) RETURNING id",
                (user_id, session_id, title),
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as exc:
        _logger.warning("chat_history.get_or_create_conversation failed: %s", exc)
        return None


def save_message(
    conversation_id: int,
    role: str,
    content: str,
    tool_called: str | None = None,
    tool_result: dict | None = None,
    sap_source: dict | None = None,
    abap_check: dict | None = None,
    abap_code: dict | None = None,
    report: dict | None = None,
    status_steps: list | None = None,
) -> None:
    """Persist a single message and bump the conversation's updated_at."""
    try:
        from db.connection import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO messages
                   (conversation_id, role, content, tool_called,
                    tool_result, sap_source, abap_check, abap_code, report, status_steps)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    conversation_id,
                    role,
                    content,
                    tool_called,
                    json.dumps(tool_result,  cls=_SafeEncoder) if tool_result  is not None else None,
                    json.dumps(sap_source,   cls=_SafeEncoder) if sap_source   is not None else None,
                    json.dumps(abap_check,   cls=_SafeEncoder) if abap_check   is not None else None,
                    json.dumps(abap_code,    cls=_SafeEncoder) if abap_code    is not None else None,
                    json.dumps(report,       cls=_SafeEncoder) if report       is not None else None,
                    json.dumps(status_steps, cls=_SafeEncoder) if status_steps is not None else '[]',
                ),
            )
            cursor.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                (conversation_id,),
            )
    except Exception as exc:
        _logger.warning("chat_history.save_message failed: %s", exc)


def list_conversations(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return conversations for a user, newest first."""
    try:
        from db.connection import query_all
        rows = query_all(
            "SELECT id, session_id, title, created_at, updated_at "
            "FROM conversations WHERE user_id = %s "
            "ORDER BY updated_at DESC LIMIT %s",
            (user_id, limit),
        )
        # Convert datetime objects to ISO strings for JSON serialisation
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("updated_at"):
                r["updated_at"] = r["updated_at"].isoformat()
        return rows
    except Exception as exc:
        _logger.warning("chat_history.list_conversations failed: %s", exc)
        return []


def get_messages(session_id: str, user_id: str) -> list[dict[str, Any]]:
    """Return all messages for a conversation, oldest first."""
    try:
        from db.connection import query_all
        rows = query_all(
            """SELECT m.id, m.role, m.content, m.tool_called,
                      m.tool_result, m.sap_source, m.abap_check, m.abap_code,
                      m.report, m.status_steps, m.created_at
               FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.session_id = %s AND c.user_id = %s
               ORDER BY m.created_at ASC""",
            (session_id, user_id),
        )
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            # JSON columns come back as strings — parse them
            for col in ("tool_result", "sap_source", "abap_check", "abap_code", "report", "status_steps"):
                val = r.get(col)
                if isinstance(val, str):
                    try:
                        r[col] = json.loads(val)
                    except Exception:
                        r[col] = [] if col == "status_steps" else None
            if not r.get("status_steps"):
                r["status_steps"] = []
        return rows
    except Exception as exc:
        _logger.warning("chat_history.get_messages failed: %s", exc)
        return []


def delete_conversation(session_id: str, user_id: str) -> bool:
    """Delete a conversation (cascades to its messages). Returns True if deleted."""
    try:
        from db.connection import execute
        n = execute(
            "DELETE FROM conversations WHERE session_id = %s AND user_id = %s",
            (session_id, user_id),
        )
        return n > 0
    except Exception as exc:
        _logger.warning("chat_history.delete_conversation failed: %s", exc)
        return False


def clear_messages(session_id: str, user_id: str) -> None:
    """Delete all messages in a conversation but keep the conversation row."""
    try:
        from db.connection import get_db
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM messages WHERE conversation_id IN ("
                "  SELECT id FROM conversations WHERE session_id = %s AND user_id = %s"
                ")",
                (session_id, user_id),
            )
    except Exception as exc:
        _logger.warning("chat_history.clear_messages failed: %s", exc)


# ── Async variants for streaming endpoint ────────────────────────────────────

async def async_get_or_create_conversation(
    user_id: str, session_id: str, first_message: str = ""
) -> int | None:
    """Async version of get_or_create_conversation — non-blocking for streaming."""
    try:
        from db.connection import async_query_one, async_execute
        row = await async_query_one(
            "SELECT id FROM conversations WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
        if row:
            return row["id"]
        title = (first_message[:80] + "…") if len(first_message) > 80 else (first_message or "New conversation")
        from db.connection import _get_async_pool
        async with _get_async_pool().connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO conversations (user_id, session_id, title) VALUES (%s, %s, %s) RETURNING id",
                    (user_id, session_id, title),
                )
                row = await cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        _logger.warning("chat_history.async_get_or_create_conversation failed: %s", exc)
        return None


async def async_save_message(
    conversation_id: int,
    role: str,
    content: str,
    tool_called: str | None = None,
    tool_result: dict | None = None,
    sap_source: dict | None = None,
    abap_check: dict | None = None,
    abap_code: dict | None = None,
    report: dict | None = None,
    status_steps: list | None = None,
) -> None:
    """Async version of save_message — non-blocking for streaming event_generator."""
    try:
        from db.connection import _get_async_pool
        async with _get_async_pool().connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO messages
                       (conversation_id, role, content, tool_called,
                        tool_result, sap_source, abap_check, abap_code, report, status_steps)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        conversation_id, role, content, tool_called,
                        json.dumps(tool_result,  cls=_SafeEncoder) if tool_result  is not None else None,
                        json.dumps(sap_source,   cls=_SafeEncoder) if sap_source   is not None else None,
                        json.dumps(abap_check,   cls=_SafeEncoder) if abap_check   is not None else None,
                        json.dumps(abap_code,    cls=_SafeEncoder) if abap_code    is not None else None,
                        json.dumps(report,       cls=_SafeEncoder) if report       is not None else None,
                        json.dumps(status_steps, cls=_SafeEncoder) if status_steps is not None else '[]',
                    ),
                )
                await cur.execute(
                    "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                    (conversation_id,),
                )
    except Exception as exc:
        _logger.warning("chat_history.async_save_message failed: %s", exc)
