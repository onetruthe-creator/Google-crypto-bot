"""
Execution worker — polls the DB for APPROVED signals and executes them.

Can run two ways:
  1. As a background thread started by the FastAPI app (default).
  2. As a standalone process: python -m app.worker
     (used with the optional brain-worker.service systemd unit)

The kill switch is checked AGAIN here as a final defense before any trade.
"""
import logging
import time
from datetime import datetime, timezone

from app.audit import audit_event
from app.db import get_conn, init_db
from app.slack import send_notification
from app.state import kill_switch_enabled, load_kill_switch_from_db

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_approved_signals(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status = 'APPROVED' ORDER BY received_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _set_status(signal_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), signal_id),
        )


def execute_signal(signal: dict) -> None:
    """
    Execute one approved trading signal.

    Replace the stub block below with your real exchange API call.
    The kill switch is checked once more here as a final safeguard.
    """
    signal_id = signal["id"]

    # ── Final kill switch check (defense-in-depth) ───────────────────────────
    load_kill_switch_from_db()
    if kill_switch_enabled():
        logger.warning("Kill switch ON — blocking execution of signal %s", signal_id)
        _set_status(signal_id, "BLOCKED_BY_KILLSWITCH")
        audit_event(
            "execution_blocked_by_killswitch", signal, signal_id=signal_id, actor="worker"
        )
        return

    logger.info(
        "Executing signal %s: %s %s %s", signal_id, signal["side"], signal["qty"], signal["symbol"]
    )
    _set_status(signal_id, "EXECUTING")
    audit_event("execution_started", signal, signal_id=signal_id, actor="worker")

    try:
        # ── TODO: replace this stub with your real exchange call ─────────────
        #
        # Example (Binance):
        #   from binance.client import Client
        #   client = Client(api_key, api_secret)
        #   result = client.create_order(
        #       symbol=signal["symbol"],
        #       side=signal["side"],          # "BUY" or "SELL"
        #       type="MARKET",
        #       quantity=signal["qty"],
        #   )
        #
        # Example (Coinbase Advanced):
        #   result = coinbase_client.create_order(...)
        #
        result = {
            "order_id": f"stub_{signal_id[:8]}",
            "status": "FILLED",
            "symbol": signal["symbol"],
            "side": signal["side"],
            "qty": signal["qty"],
        }
        # ────────────────────────────────────────────────────────────────────

        _set_status(signal_id, "EXECUTED")
        audit_event("execution_completed", result, signal_id=signal_id, actor="worker")
        send_notification(
            f":white_check_mark: *Executed:* {signal['side']} {signal['qty']} {signal['symbol']}"
            f" | Order: `{result.get('order_id', 'N/A')}`"
        )
        logger.info("Signal %s executed successfully", signal_id)

    except Exception as exc:
        logger.exception("Execution failed for signal %s: %s", signal_id, exc)
        _set_status(signal_id, "FAILED")
        audit_event(
            "execution_failed", {"error": str(exc)}, signal_id=signal_id, actor="worker"
        )
        send_notification(f":fire: *Execution FAILED* for signal `{signal_id}`: {exc}")


def run_worker(poll_interval: float = 2.0) -> None:
    """Main loop. Runs forever. Safe to call from a daemon thread."""
    init_db()
    load_kill_switch_from_db()
    logger.info("Worker started — polling every %.1fs", poll_interval)
    send_notification(
        ":robot_face: Brain worker started. Kill switch: "
        + (":skull: ON" if kill_switch_enabled() else ":white_check_mark: OFF")
    )

    while True:
        try:
            for signal in _fetch_approved_signals():
                execute_signal(signal)
        except Exception as exc:
            logger.exception("Worker loop error: %s", exc)
        time.sleep(poll_interval)


if __name__ == "__main__":
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    run_worker()
