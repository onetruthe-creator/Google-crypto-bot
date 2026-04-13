"""Kill switch state management.

Persistence: SQLite (survives reboots).
Speed: in-memory cache (avoids a DB round-trip on every signal).

IMPORTANT: is_enabled = True  => kill switch ON  => all executions BLOCKED.
           is_enabled = False => kill switch OFF => execution allowed.
"""
import threading
from datetime import datetime, timezone

from app.db import get_conn

_cache_lock = threading.Lock()
# Assume ON until the first DB read succeeds (fail-safe).
_kill_switch_cache: bool = True


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def kill_switch_enabled() -> bool:
    """Fast path: return cached kill switch state."""
    with _cache_lock:
        return _kill_switch_cache


def load_kill_switch_from_db() -> bool:
    """Read state from DB and refresh the in-memory cache. Call on startup and before execution."""
    global _kill_switch_cache
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_enabled FROM kill_switch WHERE id = 1"
        ).fetchone()
    state = bool(row["is_enabled"]) if row else True
    with _cache_lock:
        _kill_switch_cache = state
    return state


def set_kill_switch(enabled: bool, reason: str = "", updated_by: str = "system") -> None:
    """Persist kill switch state and update the cache atomically."""
    global _kill_switch_cache
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE kill_switch
            SET is_enabled = ?, reason = ?, updated_at = ?, updated_by = ?
            WHERE id = 1
            """,
            (1 if enabled else 0, reason, _utcnow(), updated_by),
        )
    with _cache_lock:
        _kill_switch_cache = enabled


def get_kill_switch_status() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM kill_switch WHERE id = 1").fetchone()
    if not row:
        return {
            "is_enabled": True,
            "reason": "unknown — row missing",
            "updated_at": None,
            "updated_by": None,
        }
    return dict(row)
