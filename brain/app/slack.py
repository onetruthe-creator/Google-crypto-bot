"""Slack integration: send messages and interactive approval requests."""
import secrets
import string

import httpx

from app.config import get_settings


def generate_confirm_code(length: int = 6) -> str:
    """Random numeric confirmation code for high-value trade approvals."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def send_approval_request(signal: dict, confirm_code: str) -> str | None:
    """
    Post an interactive Slack message with Approve / Reject / Kill Switch buttons.
    Returns the Slack message timestamp (ts) for later updates, or None on failure.
    """
    settings = get_settings()
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_CHANNEL_ID:
        return None

    signal_id = signal["id"]
    notional = float(signal.get("notional_usd") or 0)
    risk = signal.get("risk_score", "UNKNOWN")
    strategy = signal.get("strategy") or "—"
    needs_code = notional >= settings.REQUIRE_APPROVAL_THRESHOLD_USD

    risk_emoji = {
        "LOW": ":white_check_mark:",
        "MED": ":warning:",
        "HIGH": ":red_circle:",
    }.get(risk, ":question:")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":brain: Signal Approval Required"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Strategy:*\n{strategy}"},
                {"type": "mrkdwn", "text": f"*Action:*\n{signal['side']} {signal['symbol']}"},
                {"type": "mrkdwn", "text": f"*Qty:*\n{signal['qty']}"},
                {"type": "mrkdwn", "text": f"*Notional:*\n${notional:,.2f}"},
                {"type": "mrkdwn", "text": f"*Risk:*\n{risk_emoji} {risk}"},
                {"type": "mrkdwn", "text": f"*Signal ID:*\n`{signal_id}`"},
            ],
        },
    ]

    if needs_code:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":key: *High-value trade — confirmation code:* `{confirm_code}`\n"
                        "Code is embedded in the Approve button. Verify details before clicking."
                    ),
                },
            }
        )

    approve_value = f"{signal_id}:{confirm_code}" if needs_code else signal_id

    blocks.append(
        {
            "type": "actions",
            "block_id": f"approval_{signal_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Approve"},
                    "style": "primary",
                    "action_id": "approve_signal",
                    "value": approve_value,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Confirm Approval"},
                        "text": {
                            "type": "plain_text",
                            "text": f"Approve {signal['side']} {signal['qty']} {signal['symbol']}?",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes, approve"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":x: Reject"},
                    "style": "danger",
                    "action_id": "reject_signal",
                    "value": signal_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":skull: Kill Switch ON"},
                    "style": "danger",
                    "action_id": "enable_killswitch",
                    "value": signal_id,
                    "confirm": {
                        "title": {"type": "plain_text", "text": ":skull: Enable Kill Switch"},
                        "text": {
                            "type": "plain_text",
                            "text": "This will BLOCK ALL EXECUTIONS. Are you sure?",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes, kill everything"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
            ],
        }
    )

    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={
                "channel": settings.SLACK_CHANNEL_ID,
                "text": f"Signal approval: {signal['side']} {signal['symbol']}",
                "blocks": blocks,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            return data["ts"]
        return None
    except Exception:
        return None


def update_slack_message(channel: str, ts: str, text: str, emoji: str = ":ballot_box_with_check:") -> None:
    """Replace an existing Slack message after a decision is made (removes buttons)."""
    settings = get_settings()
    if not settings.SLACK_BOT_TOKEN:
        return
    try:
        httpx.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={
                "channel": channel,
                "ts": ts,
                "text": text,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} {text}"}}
                ],
            },
            timeout=10,
        )
    except Exception:
        pass


def send_notification(text: str) -> None:
    """Post a plain-text notification to the configured Slack channel."""
    settings = get_settings()
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_CHANNEL_ID:
        return
    try:
        httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
            json={"channel": settings.SLACK_CHANNEL_ID, "text": text},
            timeout=10,
        )
    except Exception:
        pass
