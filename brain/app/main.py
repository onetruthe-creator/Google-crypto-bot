"""
Brain API — central hub for the Metaclaw → Slack → Execution pipeline.

Signal lifecycle:
  RECEIVED → VALIDATED → PENDING_APPROVAL → APPROVED → EXECUTING → EXECUTED
                                          ↘ REJECTED
             ↘ BLOCKED_BY_KILLSWITCH (checked first, at every stage)
             ↘ FAILED (execution-time error)

Slack interactions arrive via Socket Mode (no public URL needed).
"""
import hashlib
import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.audit import audit_event, get_recent_audit
from app.config import get_settings
from app.db import get_conn, init_db
from app.risk import RISK_LOW, assess_risk
from app.signals import (
    create_approval_record,
    create_signal,
    get_signal,
    set_signal_status,
)
from app.slack import generate_confirm_code, send_approval_request, send_notification
from app.socket_handler import start_socket_mode
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

    # Start execution worker as background thread
    threading.Thread(target=run_worker, daemon=True, name="brain-worker").start()

    # Start Slack Socket Mode client (non-blocking, background thread)
    # Store reference on app.state to prevent garbage collection
    app.state.slack_socket = start_socket_mode()

    ks = "ON :skull:" if kill_switch_enabled() else "OFF :white_check_mark:"
    logger.info("Brain API started. Kill switch: %s", ks)
    send_notification(f":brain: *Brain API online.* Kill switch: {ks}")
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
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_metaclaw_sig(body: bytes, signature: str) -> bool:
    settings = get_settings()
    if not settings.METACLAW_WEBHOOK_SECRET:
        return True  # not configured — allow (dev only)
    expected = hmac.new(
        settings.METACLAW_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


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

    if not _verify_metaclaw_sig(body, x_metaclaw_signature):
        logger.warning("Rejected Metaclaw webhook — invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Idempotency check
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

    # Persist signal
    signal = create_signal(payload)
    signal_id = signal["id"]
    audit_event(
        "signal_received",
        {"source": payload.get("source"), "symbol": payload.get("symbol")},
        signal_id=signal_id,
    )

    # Kill switch — highest priority check
    if kill_switch_enabled():
        set_signal_status(signal_id, "BLOCKED_BY_KILLSWITCH")
        audit_event("signal_blocked_by_killswitch", signal, signal_id=signal_id)
        send_notification(
            f":skull: Signal `{signal_id}` blocked — kill switch ON. "
            f"({signal.get('side')} {signal.get('qty')} {signal.get('symbol')})"
        )
        return {"status": "blocked_by_killswitch", "signal_id": signal_id}

    # Risk assessment
    risk_score, violations = assess_risk(signal)
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET risk_score = ?, status = 'VALIDATED', updated_at = ? WHERE id = ?",
            (risk_score, _utcnow(), signal_id),
        )
    signal["risk_score"] = risk_score

    if violations:
        set_signal_status(signal_id, "REJECTED")
        audit_event("signal_rejected_policy", {"violations": violations}, signal_id=signal_id)
        send_notification(
            f":x: Signal `{signal_id}` *rejected by risk policy:*\n"
            + "\n".join(f"• {v}" for v in violations)
        )
        return {"status": "rejected_by_policy", "signal_id": signal_id, "violations": violations}

    settings = get_settings()

    # Auto-approve low-risk (only if explicitly enabled)
    if settings.AUTO_APPROVE_LOW_RISK and risk_score == RISK_LOW:
        set_signal_status(signal_id, "APPROVED")
        audit_event("signal_auto_approved", signal, signal_id=signal_id, actor="risk_engine")
        return {"status": "auto_approved", "signal_id": signal_id, "risk_score": risk_score}

    # Request Slack approval
    set_signal_status(signal_id, "PENDING_APPROVAL")
    confirm_code = generate_confirm_code()
    slack_ts = send_approval_request(signal, confirm_code)
    create_approval_record(signal_id, slack_ts, confirm_code)
    audit_event("approval_requested", {"slack_ts": slack_ts}, signal_id=signal_id)
    logger.info(
        "Approval requested for %s (%s %s %s, risk=%s)",
        signal_id, signal["side"], signal["qty"], signal["symbol"], risk_score,
    )

    return {"status": "pending_approval", "signal_id": signal_id, "risk_score": risk_score}


# ---------------------------------------------------------------------------
# Routes: Signals & Audit
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
                "SELECT * FROM signals ORDER BY received_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


@app.get("/signals/{signal_id}", dependencies=[Depends(_require_api_key)])
def get_signal_route(signal_id: str):
    signal = get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@app.get("/audit", dependencies=[Depends(_require_api_key)])
def get_audit(limit: int = 50):
    return get_recent_audit(limit)
