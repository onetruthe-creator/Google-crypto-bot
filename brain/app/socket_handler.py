"""
Slack Socket Mode client — receives interactive events (button clicks)
over a persistent outbound WebSocket connection.

No public URL or ngrok needed. The brain connects TO Slack, not the other way around.
Requires: SLACK_APP_TOKEN (xapp-) + SLACK_BOT_TOKEN (xoxb-)
"""
import logging

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from app.audit import audit_event
from app.config import get_settings
from app.signals import get_approval_record, get_signal, record_decision
from app.slack import send_notification, update_slack_message
from app.state import kill_switch_enabled, load_kill_switch_from_db, set_kill_switch

logger = logging.getLogger(__name__)


def _handle_interaction(client: SocketModeClient, req: SocketModeRequest) -> None:
    """Process a Slack button click. Must acknowledge within 3 seconds."""
    # Acknowledge immediately — Slack requires this within 3s
    client.send_socket_mode_response(
        SocketModeResponse(envelope_id=req.envelope_id)
    )

    payload = req.payload
    user_id = payload.get("user", {}).get("id", "")
    settings = get_settings()
    channel_id = payload.get("channel", {}).get("id") or settings.SLACK_CHANNEL_ID
    message_ts = payload.get("message", {}).get("ts", "")

    # Only the configured admin may take action
    if settings.SLACK_ADMIN_USER_ID and user_id != settings.SLACK_ADMIN_USER_ID:
        logger.warning("Unauthorized Slack action from user %s — ignored", user_id)
        return

    actions = payload.get("actions", [])
    if not actions:
        return

    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")

    # ── Kill Switch ──────────────────────────────────────────────────────────
    if action_id == "enable_killswitch":
        set_kill_switch(True, reason=f"Enabled via Slack by {user_id}", updated_by=user_id)
        audit_event("killswitch_enabled", {"via": "slack_button"}, actor=user_id)
        if value:
            record_decision(value, "REJECTED", user_id)
            audit_event("signal_rejected", {"reason": "kill_switch_activated"}, signal_id=value, actor=user_id)
        if message_ts:
            update_slack_message(channel_id, message_ts, f":skull: Kill switch ENABLED by <@{user_id}>. All executions blocked.", ":skull:")
        send_notification(f":skull: *Kill switch ENABLED* by <@{user_id}>. All trades are blocked.")
        return

    # ── Reject ───────────────────────────────────────────────────────────────
    if action_id == "reject_signal":
        signal = get_signal(value)
        if not signal:
            return
        if signal["status"] not in ("PENDING_APPROVAL", "VALIDATED", "RECEIVED"):
            return
        record_decision(value, "REJECTED", user_id)
        audit_event("signal_rejected", {"decided_by": user_id}, signal_id=value, actor=user_id)
        if message_ts:
            update_slack_message(channel_id, message_ts, f":x: Rejected by <@{user_id}>", ":x:")
        return

    # ── Approve ──────────────────────────────────────────────────────────────
    if action_id == "approve_signal":
        parts = value.split(":", 1)
        signal_id = parts[0]
        provided_code = parts[1] if len(parts) > 1 else None

        signal = get_signal(signal_id)
        if not signal:
            return
        if signal["status"] not in ("PENDING_APPROVAL", "VALIDATED", "RECEIVED"):
            return

        # Verify confirmation code for high-value signals
        if provided_code is not None:
            approval = get_approval_record(signal_id)
            if not approval or approval["confirm_code"] != provided_code:
                audit_event("approval_code_mismatch", {"signal_id": signal_id}, actor=user_id)
                return

        # Final kill switch guard
        load_kill_switch_from_db()
        if kill_switch_enabled():
            return

        record_decision(signal_id, "APPROVED", user_id)
        audit_event("signal_approved", {"decided_by": user_id}, signal_id=signal_id, actor=user_id)
        if message_ts:
            update_slack_message(channel_id, message_ts, f":white_check_mark: Approved by <@{user_id}>", ":white_check_mark:")
        send_notification(
            f":white_check_mark: Signal `{signal_id}` *APPROVED* by <@{user_id}>. Queued for execution."
        )


def start_socket_mode() -> SocketModeClient | None:
    """
    Connect to Slack via Socket Mode.
    Non-blocking — the SDK maintains the connection in a background thread.
    Returns the client (keep a reference to prevent GC), or None if not configured.
    """
    settings = get_settings()

    if not settings.SLACK_APP_TOKEN:
        logger.warning("SLACK_APP_TOKEN not set — Slack button interactions disabled")
        return None
    if not settings.SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set — cannot send Slack messages")
        return None

    web_client = WebClient(token=settings.SLACK_BOT_TOKEN)
    sc = SocketModeClient(app_token=settings.SLACK_APP_TOKEN, web_client=web_client)

    def _listener(client: SocketModeClient, req: SocketModeRequest):
        if req.type == "interactive":
            try:
                _handle_interaction(client, req)
            except Exception as exc:
                logger.exception("Socket Mode interaction error: %s", exc)

    sc.socket_mode_request_listeners.append(_listener)
    sc.connect()  # starts background thread, returns immediately
    logger.info("Slack Socket Mode connected (local mode — no public URL needed)")
    return sc
