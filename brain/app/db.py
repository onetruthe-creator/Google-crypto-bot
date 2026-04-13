"""SQLite database setup and thread-safe connection helper."""
import sqlite3
import threading
from contextlib import contextmanager

from app.config import get_settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    qty              REAL NOT NULL,
    price            REAL,
    strategy         TEXT,
    notional_usd     REAL,
    risk_score       TEXT,
    status           TEXT NOT NULL DEFAULT 'RECEIVED',
    received_at      TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    idempotency_key  TEXT UNIQUE,
    raw_payload      TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id        TEXT NOT NULL,
    requested_at     TEXT NOT NULL,
    slack_message_ts TEXT,
    confirm_code     TEXT,
    decision         TEXT,
    decided_at       TEXT,
    decided_by       TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Single-row table; id is always 1.
-- is_enabled = 1 means kill switch is ON (all executions BLOCKED). Safe default.
CREATE TABLE IF NOT EXISTS kill_switch (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    is_enabled  INTEGER NOT NULL DEFAULT 1,
    reason      TEXT,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT
);

-- Append-only event stream. Never update or delete rows here.
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    signal_id    TEXT,
    payload_json TEXT,
    actor        TEXT,
    created_at   TEXT NOT NULL
);
"""


def get_db_path() -> str:
    return get_settings().DATABASE_PATH


@contextmanager
def get_conn():
    """Yield a committed SQLite connection. Serialises all DB access via a lock."""
    with _lock:
        conn = sqlite3.connect(get_db_path(), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db():
    """Create tables and seed the kill_switch row (ON by default)."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT OR IGNORE INTO kill_switch (id, is_enabled, reason, updated_at, updated_by)
            VALUES (1, 1, 'Default safe state on first boot', datetime('now'), 'system')
            """
        )
