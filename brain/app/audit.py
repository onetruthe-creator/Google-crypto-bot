"""Append-only audit log. Never update or delete rows."""
import json
from datetime import datetime, timezone

from app.db import get_conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_event(
    event_type: str,
    payload: dict = None,
    signal_id: str = None,
    actor: str = None,
) -> None:
    """Write one immutable audit record."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (event_type, signal_id, payload_json, actor, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, signal_id, json.dumps(payload or {}), actor, _utcnow()),
        )


def get_recent_audit(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
