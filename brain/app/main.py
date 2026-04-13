"""
Brain API — central hub for the Metaclaw → Slack → Execution pipeline.

Signal lifecycle:
  RECEIVED → VALIDATED → PENDING_APPROVAL → APPROVED → EXECUTING → EXECUTED
                                          ↘ REJECTED
             ↘ BLOCKED_BY_KILLSWITCH (at any pre-execution stage)
             ↘ FAILED (execution-time error)
"""
import hashlib
import hmac
import json
import logging
import threading
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.audit import audit_event, get_recent_audit
from app.config import get_settings
from app.db import get_conn, init_db
from app.risk import RISK_LOW, assess_risk
from app.slack import (
    generate_confirm_code,
    send_approval_request,
    send_notification,
    update_slack_message,
    verify_slack_signature,
)
from app.state import (
    get_kill_switch_status,
    kill_switch_enabled,
    load_kill_switch_from_db,
    set_kill_switch,
)
from app.worker import run_worker

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_kill_switch_from_db()
    t = threading.Thread(target=run_worker, daemon=True, name="brain-worker")
    t.start()
    ks_state = "ON :skull:" if kill_switch_enabled() else "OFF :white_check_mark:"
    logger.info("Brain API started. Kill switch: %s", ks_state)
    send_notification(f":brain: *Brain API online.* Kill switch: {ks_state}")
    yield
    logger.info("Brain API shutting down.")


app = FastAPI(title="Brain API", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_api_key(authorization: str = Header(default="")) -> None:
    settings = get_settings()
    key = settings.BRAIN_API_KEY
    if not key:
        if settings.APP_ENV == "prod":
            raise HTTPException(
                status_code=503, detail="BRAIN_API_KEY not configured — set it in .env"
            )
        return  # dev mode: skip auth
    if authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_metaclaw_sig(body: bytes, signature: str) -> bool:
    settings = get_settings()
    if not settings.METACLAW_WEBHOOK_SECRET:
        return True  # secret not configured — allow (dev mode only)
    expected = hmac.new(
        settings.METACLAW_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def _create_signal(payload: dict) -> dict:
    signal_id = str(uuid.uuid4())
    qty = float(payload.get("qty") or 0)
    price = float(payload["price"]) if payload.get("price") else None
    notional = float(
        payload.get("notional_usd") or (qty * price if price else 0)
    )
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


def _get_signal(signal_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    return dict(row) if row else None


def _set_signal_status(signal_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), signal_id),
        )


def _create_approval_record(signal_id: str, slack_ts: str | None, confirm_code: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO approvals (signal_id, requested_at, slack_message_ts, confirm_code)
            VALUES (?, ?, ?, ?)
            """,
            (signal_id, _utcnow(), slack_ts, confirm_code),
        )


def _get_approval_record(signal_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM approvals WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
    return dict(row) if row else None


def _record_decision(signal_id: str, decision: str, decided_by: str) -> None:
    new_status = "APPROVED" if decision == "APPROVED" else "REJECTED"
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE approvals
            SET decision = ?, decided_at = ?, decided_by = ?
            WHERE signal_id = ? AND decision IS NULL
            """,
            (decision, _utcnow(), decided_by, signal_id),
        )
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _utcnow(), signal_id),
        )


# ---------------------------------------------------------------------------
# Route: Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
def health():
    ks = get_kill_switch_status()
    return {
        "status": "ok",
        "kill_switch": "ON" if ks["is_enabled"] else "OFF",
        "kill_switch_reason": ks.get("reason"),
        "kill_switch_updated_by": ks.get("updated_by"),
    }


# ---------------------------------------------------------------------------
# Routes: Kill Switch
# ---------------------------------------------------------------------------

@app.get("/killswitch/status", dependencies=[Depends(_require_api_key)])
def killswitch_status():
    return get_kill_switch_status()


@app.post("/killswitch/enable", dependencies=[Depends(_require_api_key)])
async def killswitch_enable(request: Request):
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    reason = body.get("reason", "Manual enable via API")
    actor = body.get("actor", "api")
    set_kill_switch(True, reason=reason, updated_by=actor)
    audit_event("killswitch_enabled", {"reason": reason}, actor=actor)
    send_notification(f":skull: *Kill switch ENABLED* by `{actor}`. Reason: _{reason}_")
    return {"status": "kill_switch_enabled", "reason": reason}


@app.post("/killswitch/disable", dependencies=[Depends(_require_api_key)])
async def killswitch_disable(request: Request):
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    reason = body.get("reason", "Manual disable via API")
    actor = body.get("actor", "api")
    set_kill_switch(False, reason=reason, updated_by=actor)
    audit_event("killswitch_disabled", {"reason": reason}, actor=actor)
    send_notification(f":white_check_mark: *Kill switch DISABLED* by `{actor}`. Reason: _{reason}_")
    return {"status": "kill_switch_disabled", "reason": reason}


# ---------------------------------------------------------------------------
# Route: Metaclaw Webhook
# ---------------------------------------------------------------------------

@app.post("/webhook/metaclaw")
async def metaclaw_webhook(
    request: Request,
    x_metaclaw_signature: str = Header(default=""),
):
    body = await request.body()

    # 1. Verify webhook signature
    if not _verify_metaclaw_sig(body, x_metaclaw_signature):
        logger.warning("Rejected Metaclaw webhook — invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 2. Idempotency check
    idem_key = payload.get("idempotency_key")
    if idem_key:
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id, status FROM signals WHERE idempotency_key = ?", (idem_key,)
            ).fetchone()
        if existing:
            return {
                "status": "duplicate",
                "signal_id": existing["id"],
                "existing_status": existing["status"],
            }

    # 3. Persist signal
    signal = _create_signal(payload)
    signal_id = signal["id"]
    audit_event(
        "signal_received",
        {"source": payload.get("source"), "symbol": payload.get("symbol")},
        signal_id=signal_id,
    )

    # 4. Kill switch — first and highest priority check
    if kill_switch_enabled():
        _set_signal_status(signal_id, "BLOCKED_BY_KILLSWITCH")
        audit_event("signal_blocked_by_killswitch", signal, signal_id=signal_id)
        logger.info("Signal %s blocked by kill switch", signal_id)
        send_notification(
            f":skull: Signal `{signal_id}` blocked — kill switch is ON. "
            f"({signal.get('side')} {signal.get('qty')} {signal.get('symbol')})"
        )
        return {"status": "blocked_by_killswitch", "signal_id": signal_id}

    # 5. Risk assessment
    risk_score, violations = assess_risk(signal)
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET risk_score = ?, status = 'VALIDATED', updated_at = ? WHERE id = ?",
            (risk_score, _utcnow(), signal_id),
        )
    signal["risk_score"] = risk_score

    if violations:
        _set_signal_status(signal_id, "REJECTED")
        audit_event("signal_rejected_policy", {"violations": violations}, signal_id=signal_id)
        send_notification(
            f":x: Signal `{signal_id}` *rejected by risk policy:*\n"
            + "\n".join(f"• {v}" for v in violations)
        )
        return {"status": "rejected_by_policy", "signal_id": signal_id, "violations": violations}

    settings = get_settings()

    # 6. Auto-approve low-risk signals (only if explicitly enabled)
    if settings.AUTO_APPROVE_LOW_RISK and risk_score == RISK_LOW:
        _set_signal_status(signal_id, "APPROVED")
        audit_event("signal_auto_approved", signal, signal_id=signal_id, actor="risk_engine")
        return {"status": "auto_approved", "signal_id": signal_id, "risk_score": risk_score}

    # 7. Request Slack approval
    _set_signal_status(signal_id, "PENDING_APPROVAL")
    confirm_code = generate_confirm_code()
    slack_ts = send_approval_request(signal, confirm_code)
    _create_approval_record(signal_id, slack_ts, confirm_code)
    audit_event("approval_requested", {"slack_ts": slack_ts}, signal_id=signal_id)
    logger.info(
        "Approval requested for signal %s (%s %s %s, risk=%s)",
        signal_id, signal["side"], signal["qty"], signal["symbol"], risk_score,
    )

    return {
        "status": "pending_approval",
        "signal_id": signal_id,
        "risk_score": risk_score,
    }


# ---------------------------------------------------------------------------
# Route: Slack Actions (button callbacks)
# ---------------------------------------------------------------------------

@app.post("/slack/actions")
async def slack_actions(request: Request):
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(body, timestamp, signature):
        logger.warning("Rejected Slack action — invalid signature")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    # Slack sends form-encoded: payload=<json>
    form = urllib.parse.parse_qs(body.decode("utf-8"))
    payload = json.loads(form.get("payload", ["{}"])[0])

    user_id = payload.get("user", {}).get("id", "")
    settings = get_settings()
    channel_id = payload.get("channel", {}).get("id") or settings.SLACK_CHANNEL_ID
    message_ts = payload.get("message", {}).get("ts", "")

    # Authorization: only the configured admin Slack user may take action
    if settings.SLACK_ADMIN_USER_ID and user_id != settings.SLACK_ADMIN_USER_ID:
        logger.warning("Unauthorized Slack action attempted by user %s", user_id)
        return JSONResponse(
            {"text": ":lock: Unauthorized. Only the designated admin can approve/reject signals."}
        )

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse({"text": "No action found in payload."})

    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")

    # ── Kill Switch ──────────────────────────────────────────────────────────
    if action_id == "enable_killswitch":
        set_kill_switch(
            True,
            reason=f"Enabled via Slack by {user_id}",
            updated_by=user_id,
        )
        audit_event("killswitch_enabled", {"via": "slack_button"}, actor=user_id)
        # Also reject the signal that triggered the button
        if value:
            _record_decision(value, "REJECTED", user_id)
            audit_event(
                "signal_rejected",
                {"reason": "kill_switch_activated"},
                signal_id=value,
                actor=user_id,
            )
        if message_ts:
            update_slack_message(
                channel_id,
                message_ts,
                f":skull: Kill switch ENABLED by <@{user_id}>. All executions blocked.",
                ":skull:",
            )
        send_notification(
            f":skull: *Kill switch ENABLED* by <@{user_id}>. All trades are now blocked."
        )
        return JSONResponse({"text": ":skull: Kill switch enabled. All executions blocked."})

    # ── Reject ───────────────────────────────────────────────────────────────
    if action_id == "reject_signal":
        signal_id = value
        signal = _get_signal(signal_id)
        if not signal:
            return JSONResponse({"text": f"Signal `{signal_id}` not found."})
        if signal["status"] not in ("PENDING_APPROVAL", "VALIDATED", "RECEIVED"):
            return JSONResponse(
                {"text": f"Signal `{signal_id}` is already `{signal['status']}` — no action taken."}
            )
        _record_decision(signal_id, "REJECTED", user_id)
        audit_event(
            "signal_rejected", {"decided_by": user_id}, signal_id=signal_id, actor=user_id
        )
        if message_ts:
            update_slack_message(
                channel_id,
                message_ts,
                f":x: Rejected by <@{user_id}>",
                ":x:",
            )
        return JSONResponse({"text": f":x: Signal `{signal_id}` rejected."})

    # ── Approve ──────────────────────────────────────────────────────────────
    if action_id == "approve_signal":
        # High-value value format: "signal_id:confirm_code"
        # Normal value format:     "signal_id"
        parts = value.split(":", 1)
        signal_id = parts[0]
        provided_code = parts[1] if len(parts) > 1 else None

        signal = _get_signal(signal_id)
        if not signal:
            return JSONResponse({"text": f"Signal `{signal_id}` not found."})
        if signal["status"] not in ("PENDING_APPROVAL", "VALIDATED", "RECEIVED"):
            return JSONResponse(
                {"text": f"Signal `{signal_id}` is already `{signal['status']}` — no action taken."}
            )

        # Verify confirmation code for high-value signals
        if provided_code is not None:
            approval = _get_approval_record(signal_id)
            stored_code = approval["confirm_code"] if approval else None
            if stored_code != provided_code:
                audit_event(
                    "approval_code_mismatch", {"signal_id": signal_id}, actor=user_id
                )
                return JSONResponse(
                    {"text": ":lock: Confirmation code mismatch. Approval denied. Signal remains pending."}
                )

        # Final kill switch guard before approving
        load_kill_switch_from_db()
        if kill_switch_enabled():
            return JSONResponse(
                {
                    "text": (
                        ":skull: Kill switch is currently ON — cannot approve. "
                        "Use `/killswitch disable` via the API to re-enable trading first."
                    )
                }
            )

        _record_decision(signal_id, "APPROVED", user_id)
        audit_event(
            "signal_approved", {"decided_by": user_id}, signal_id=signal_id, actor=user_id
        )
        if message_ts:
            update_slack_message(
                channel_id,
                message_ts,
                f":white_check_mark: Approved by <@{user_id}> — queued for execution.",
                ":white_check_mark:",
            )
        send_notification(
            f":white_check_mark: Signal `{signal_id}` *APPROVED* by <@{user_id}>. Queued for execution."
        )
        return JSONResponse(
            {"text": f":white_check_mark: Signal `{signal_id}` approved. Execution queued."}
        )

    return JSONResponse({"text": f"Unknown action `{action_id}`."})


# ---------------------------------------------------------------------------
# Routes: Signals & Audit (management)
# ---------------------------------------------------------------------------

@app.get("/signals", dependencies=[Depends(_require_api_key)])
def list_signals(limit: int = 20, status: str = None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM signals WHERE status = ? ORDER BY received_at DESC LIMIT ?",
                (status.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY received_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/signals/{signal_id}", dependencies=[Depends(_require_api_key)])
def get_signal(signal_id: str):
    signal = _get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@app.get("/audit", dependencies=[Depends(_require_api_key)])
def get_audit(limit: int = 50):
    return get_recent_audit(limit)
