#!/usr/bin/env python3
"""
SOVEREIGN Slack Bridge — Google Crypto Bot Connection
Port: 5003

Translates Slack events into SOVEREIGN tasks and posts status back to the operator.
Commands: status, task <desc>, plan <goal>, help
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

# ── Configuration ─────────────────────────────────────────────────────────────

PORT = 5003
TIMEZONE = ZoneInfo("America/Denver")
BASE_DIR = Path(os.getenv("SOVEREIGN_DIR", str(Path.home() / "sovereign")))
LOG_PATH = BASE_DIR / "slack_bridge.log"

SOVEREIGN_URL = os.getenv("SOVEREIGN_URL", "http://localhost:8888")
METACLAW_URL = os.getenv("METACLAW_URL", "http://localhost:5002")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#sovereign")
SLACK_API = "https://slack.com/api"

# ── Logging ───────────────────────────────────────────────────────────────────

BASE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("SlackBridge")

app = Flask(__name__)

# ── Slack API ─────────────────────────────────────────────────────────────────

def _slack_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def post_message(text: str, channel: str = SLACK_DEFAULT_CHANNEL,
                 thread_ts: Optional[str] = None) -> Dict:
    if not SLACK_BOT_TOKEN:
        log.warning("SLACK_BOT_TOKEN not configured — message dropped")
        return {"ok": False, "error": "no_token"}

    payload: Dict[str, Any] = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        r = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers=_slack_headers(),
            json=payload,
            timeout=10,
        )
        data = r.json()
        if not data.get("ok"):
            log.error("Slack error: %s", data.get("error"))
        return data
    except Exception as exc:
        log.error("Slack post failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def post_blocks(blocks: List[Dict], channel: str = SLACK_DEFAULT_CHANNEL) -> Dict:
    if not SLACK_BOT_TOKEN:
        return {"ok": False, "error": "no_token"}
    try:
        r = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers=_slack_headers(),
            json={"channel": channel, "blocks": blocks},
            timeout=10,
        )
        return r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

# ── Message Formatting ────────────────────────────────────────────────────────

def _agent_icon(status: str) -> str:
    return {"online": "✅", "degraded": "⚠️", "offline": "🔴"}.get(status, "❓")


def format_status(data: Dict) -> str:
    agents = data.get("agents", [])
    lines = ["*SOVEREIGN Status*", ""]
    for a in agents:
        icon = _agent_icon(a.get("status", "unknown"))
        lines.append(f"{icon}  `{a.get('agent', '?')}` — {a.get('status', '?')}")

    events = data.get("recent_events", [])
    if events:
        lines.append("\n*Recent Events*")
        for e in events[:6]:
            ts = (e.get("ts") or "")[:19]
            lines.append(f"`{ts}` [{e.get('level','?')}] {e.get('source','?')}: {e.get('event','?')}")

    pending = data.get("pending_tasks", [])
    if pending:
        lines.append(f"\n*Pending Tasks:* {len(pending)}")

    return "\n".join(lines)


def format_plan(plan: Dict) -> str:
    steps = plan.get("steps", [])
    priority = plan.get("priority", "?")
    lines = [
        f"*Plan* `{plan.get('plan_id','?')}` — Priority {priority}",
        f"Goal: _{plan.get('goal','')}_",
        "",
    ]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)

# ── Command Dispatch ──────────────────────────────────────────────────────────

_HELP_TEXT = (
    "*SOVEREIGN Commands*\n"
    "• `status` — show all agent health and recent events\n"
    "• `task <description>` — dispatch a task to the Super Agent\n"
    "• `plan <goal>` — decompose a goal into steps via MetaClaw\n"
    "• `diagnose <component> <symptoms>` — run SRE diagnosis\n"
    "• `recover <agent>` — trigger recovery reasoning for an agent\n"
    "• `help` — show this message"
)


def handle_command(text: str, channel: str, thread_ts: Optional[str] = None) -> None:
    """Parse and dispatch a Slack command. Runs in a background thread."""
    text = text.strip()
    lower = text.lower()

    try:
        if lower in ("status", "health", "ping"):
            r = requests.get(f"{SOVEREIGN_URL}/status", timeout=6)
            reply = format_status(r.json())

        elif lower.startswith("task "):
            description = text[5:].strip()
            r = requests.post(
                f"{SOVEREIGN_URL}/task",
                json={"description": description},
                timeout=90,
            )
            d = r.json()
            agent = d.get("agent", "?")
            task_id = d.get("task_id", "?")
            result_text = json.dumps(d.get("result", {}))[:300]
            reply = f"✓ Task `{task_id}` dispatched to `{agent}`\n```{result_text}```"

        elif lower.startswith("plan "):
            goal = text[5:].strip()
            r = requests.post(f"{METACLAW_URL}/plan", json={"goal": goal}, timeout=90)
            reply = format_plan(r.json())

        elif lower.startswith("diagnose "):
            parts = text[9:].split(" ", 1)
            component = parts[0]
            symptoms = parts[1] if len(parts) > 1 else "unspecified"
            r = requests.post(
                f"{METACLAW_URL}/diagnose",
                json={"component": component, "symptoms": symptoms},
                timeout=90,
            )
            data = r.json()
            reply = f"*Diagnosis: {component}*\n```{data.get('response','(no response)')[:800]}```"

        elif lower.startswith("recover "):
            agent = text[8:].strip()
            r = requests.post(
                f"{SOVEREIGN_URL}/agents/recover",
                json={"agent": agent},
                timeout=30,
            )
            d = r.json()
            plan_text = json.dumps(d.get("recovery_plan", {}), indent=2)[:600]
            reply = f"*Recovery plan for `{agent}`:*\n```{plan_text}```"

        elif lower in ("help", "?", "commands"):
            reply = _HELP_TEXT

        else:
            reply = f"Unknown command: `{text}`\nTry `help` to see available commands."

    except requests.Timeout:
        reply = "⚠️ SOVEREIGN did not respond in time. Check service health."
    except Exception as exc:
        reply = f"🔴 Error: {exc}"
        log.error("Command error: %s", exc)

    post_message(reply, channel, thread_ts)

# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({
        "status": "online",
        "service": "SlackBridge",
        "slack_configured": bool(SLACK_BOT_TOKEN),
        "default_channel": SLACK_DEFAULT_CHANNEL,
        "ts": datetime.now(TIMEZONE).isoformat(),
    })


@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json or {}

    # Slack URL verification (one-time setup)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge", "")})

    event = data.get("event", {})
    event_type = event.get("type", "")

    if event_type == "app_mention":
        raw_text = event.get("text", "")
        # Strip the bot mention prefix (<@UXXXXXX> ...)
        command_text = raw_text.split(">", 1)[-1].strip() if ">" in raw_text else raw_text.strip()
        channel = event.get("channel", SLACK_DEFAULT_CHANNEL)
        thread_ts = event.get("thread_ts") or event.get("ts")
        threading.Thread(
            target=handle_command,
            args=(command_text, channel, thread_ts),
            daemon=True,
        ).start()

    return jsonify({"ok": True})


@app.route("/notify", methods=["POST"])
def notify():
    """Internal endpoint — other services post alerts here."""
    data = request.json or {}
    text = data.get("text", "").strip()
    channel = data.get("channel", SLACK_DEFAULT_CHANNEL)
    if not text:
        return jsonify({"error": "text required"}), 400
    result = post_message(text, channel)
    return jsonify(result)


@app.route("/status-post", methods=["POST"])
def status_post():
    """Push a SOVEREIGN status update to Slack."""
    data = request.json or {}
    channel = data.get("channel", SLACK_DEFAULT_CHANNEL)
    try:
        r = requests.get(f"{SOVEREIGN_URL}/status", timeout=6)
        msg = format_status(r.json())
    except Exception as exc:
        msg = f"🔴 SOVEREIGN unreachable: {exc}"
    result = post_message(msg, channel)
    return jsonify(result)

# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not SLACK_BOT_TOKEN:
        log.warning("SLACK_BOT_TOKEN not set — Slack posting disabled")
    log.info("Slack Bridge online — port %d (channel: %s)", PORT, SLACK_DEFAULT_CHANNEL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
