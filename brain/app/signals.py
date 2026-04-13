"""Signal and approval CRUD operations — shared between main.py and socket_handler.py."""
import json
import uuid
from datetime import datetime, timezone

from app.db import get_conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_signal(payload: dict) -> dict:
    signal_id = str(uuid.uuid4())
    qty = float(payload.get("qty") or 0)
    price = float(payload["price"]) if payload.get("price") else None
    notional = float(payload.get("notional_usd") or (qty * price if price else 0))
    idempotency_key = payload.get("idempotency_key") or signal_id
    now = _utcnow()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO signals
                (id, source, symbol, side, qty, price, strategy, notional_usd,
                 risk_score, status, received_at, updated_at, idempotency_key, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'RECEIVED', ?, ?, ?, ?)
            """,
            (
                signal_id,
                payload.get("source", "metaclaw"),
                (payload.get("symbol") or "").upper(),
                (payload.get("side") or "").upper(),
                qty,
                price,
                payload.get("strategy"),
                notional,
                now,
                now,
                idempotency_key,
                json.dumps(payload),
            ),
        )
    return {**payload, "id": signal_id, "notional_usd": notional, "received_at": now}


def get_signal(signal_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    return dict(row) if row else None


def set_signal_status(signal_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), signal_id),
        )


def create_approval_record(signal_id: str, slack_ts: str | None, confirm_code: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO approvals (signal_id, requested_at, slack_message_ts, confirm_code)
            VALUES (?, ?, ?, ?)
            """,
            (signal_id, _utcnow(), slack_ts, confirm_code),
        )


def get_approval_record(signal_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
    return dict(row) if row else None


def record_decision(signal_id: str, decision: str, decided_by: str) -> None:
    new_status = "APPROVED" if decision == "APPROVED" else "REJECTED"
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE approvals SET decision = ?, decided_at = ?, decided_by = ?
            WHERE signal_id = ? AND decision IS NULL
            """,
            (decision, _utcnow(), decided_by, signal_id),
        )
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _utcnow(), signal_id),
        )
