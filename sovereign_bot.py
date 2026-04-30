#!/usr/bin/env python3
"""
SOVEREIGN Slack Bot — Socket Mode
Connects to Slack without a public URL.
Requires:
  SLACK_BOT_TOKEN  = xoxb-...
  SLACK_APP_TOKEN  = xapp-...  (Socket Mode app-level token)
  SOVEREIGN_URL    = http://localhost:8888
  METACLAW_URL     = http://localhost:5002
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Config ────────────────────────────────────────────────────────────────────

SLACK_BOT_TOKEN  = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN  = os.environ["SLACK_APP_TOKEN"]
SOVEREIGN_URL    = os.getenv("SOVEREIGN_URL", "http://localhost:8888")
METACLAW_URL     = os.getenv("METACLAW_URL",  "http://localhost:5002")
TIMEZONE         = ZoneInfo("America/Denver")
BASE_DIR         = Path(os.getenv("SOVEREIGN_DIR", str(Path.home() / "sovereign")))
LOG_PATH         = BASE_DIR / "sovereign_bot.log"

BASE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("SovereignBot")

app = App(token=SLACK_BOT_TOKEN)

# ── Helpers ───────────────────────────────────────────────────────────────────

def sovereign(path: str, method: str = "GET", body: Optional[dict] = None, timeout: int = 90) -> dict:
    url = f"{SOVEREIGN_URL}{path}"
    try:
        if method == "POST":
            r = requests.post(url, json=body or {}, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def metaclaw(path: str, body: dict, timeout: int = 120) -> dict:
    try:
        r = requests.post(f"{METACLAW_URL}{path}", json=body, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _agent_icon(status: str) -> str:
    return {"online": "✅", "degraded": "⚠️", "offline": "🔴", "unknown": "❓"}.get(status, "❓")


def format_status(data: dict) -> str:
    agents = data.get("agents", {})
    lines = ["*SOVEREIGN System Status*", ""]

    if isinstance(agents, list):
        for a in agents:
            icon = _agent_icon(a.get("status", "unknown"))
            lines.append(f"{icon}  `{a.get('agent','?')}` — {a.get('status','?')}")
    else:
        for name, info in agents.items():
            icon = _agent_icon(info.get("state", "unknown"))
            lines.append(f"{icon}  `{name}` — {info.get('state','?')}")

    events = data.get("recent_events", [])
    if events:
        lines.append("\n*Recent Events*")
        for e in events[:5]:
            ts = (e.get("ts") or e.get("timestamp") or "")[:19]
            lines.append(f"`{ts}` [{e.get('level','?')}] {e.get('source',e.get('event_type','?'))}: {e.get('event',e.get('description','?'))}")

    pending = data.get("pending_tasks", [])
    if pending:
        lines.append(f"\n⏳ *Pending tasks:* {len(pending)}")

    return "\n".join(lines)

# ── Command Parser ────────────────────────────────────────────────────────────

def dispatch(text: str) -> str:
    text  = text.strip()
    lower = text.lower()

    # status / health / ping
    if lower in ("status", "health", "ping", "s"):
        data = sovereign("/status")
        if "error" in data:
            return f"🔴 SOVEREIGN unreachable: `{data['error']}`"
        return format_status(data)

    # task <description>
    if lower.startswith("task "):
        desc = text[5:].strip()
        data = sovereign("/task", method="POST", body={"description": desc})
        if "error" in data:
            return f"🔴 Task failed: `{data['error']}`"
        return (
            f"✅ Task `{data.get('task_id','?')}` → `{data.get('agent','?')}`\n"
            f"```{json.dumps(data.get('result',{}), indent=2)[:400]}```"
        )

    # plan <goal>
    if lower.startswith("plan "):
        goal = text[5:].strip()
        data = metaclaw("/plan", {"goal": goal})
        if "error" in data:
            return f"🔴 Plan failed: `{data['error']}`"
        steps = data.get("steps", [])
        lines = [f"*Plan `{data.get('plan_id','?')}` — Priority {data.get('priority','?')}*",
                 f"Goal: _{goal}_", ""]
        lines += [f"{i+1}. {s}" for i, s in enumerate(steps)]
        return "\n".join(lines)

    # ask / reason <prompt>
    if lower.startswith("ask ") or lower.startswith("reason "):
        prompt = text.split(" ", 1)[1].strip()
        data = metaclaw("/reason", {"prompt": prompt})
        if "error" in data:
            return f"🔴 MetaClaw error: `{data['error']}`"
        reply = data.get("response", "No response.")
        return f"🧠 *MetaClaw [{data.get('domain','?')}]*\n{reply[:800]}"

    # chat <message> — send to SOVEREIGN's /chat endpoint
    if lower.startswith("chat "):
        msg = text[5:].strip()
        data = sovereign("/chat", method="POST", body={"message": msg}, timeout=120)
        if "error" in data:
            return f"🔴 Chat error: `{data['error']}`"
        return data.get("response", "No response.")

    # diagnose <component> <symptoms>
    if lower.startswith("diagnose "):
        parts = text[9:].split(" ", 1)
        comp  = parts[0]
        symp  = parts[1] if len(parts) > 1 else "unspecified"
        data  = metaclaw("/diagnose", {"component": comp, "symptoms": symp})
        reply = data.get("response", data.get("error", "No response."))
        return f"🔍 *Diagnosis: {comp}*\n```{reply[:800]}```"

    # recover <agent>
    if lower.startswith("recover "):
        agent = text[8:].strip()
        data  = sovereign("/agents/recover", method="POST", body={"agent": agent})
        plan  = json.dumps(data.get("recovery_plan", data), indent=2)[:600]
        return f"🔧 *Recovery plan for `{agent}`:*\n```{plan}```"

    # tasks
    if lower in ("tasks", "queue"):
        data = sovereign("/tasks?limit=10")
        if isinstance(data, list):
            if not data:
                return "No tasks yet."
            lines = [f"`{t.get('status','?')}` `{t.get('agent','?')}` — {(t.get('description') or '')[:60]}"
                     for t in data]
            return "*Recent Tasks*\n" + "\n".join(lines)
        return str(data)

    # memory
    if lower == "memory":
        data = sovereign("/memory")
        if isinstance(data, list):
            if not data:
                return "Memory is empty."
            lines = [f"`{m.get('namespace','?')}/{m.get('key','?')}` = {str(m.get('value',''))[:60]}"
                     for m in data[:15]]
            return "*Memory Store*\n" + "\n".join(lines)
        # legacy format {"history":[...]}
        history = data.get("history", [])
        return f"Conversation history: {len(history)} entries."

    # events
    if lower in ("events", "log"):
        data = sovereign("/events?limit=10")
        if isinstance(data, list):
            lines = [f"`{(e.get('ts') or '')[:19]}` [{e.get('level','?')}] {e.get('source','?')}: {e.get('event','?')}"
                     for e in data]
            return "*Event Log*\n" + "\n".join(lines) if lines else "No events."
        return str(data)

    # briefing
    if lower in ("briefing", "brief", "b"):
        data = sovereign("/briefing")
        cached = " _(cached)_" if data.get("cached") else ""
        return f"📋 *Briefing*{cached}\n{data.get('briefing', data.get('error','No briefing.'))}"

    # clear
    if lower == "clear":
        data = sovereign("/clear", method="POST")
        return f"🗑️ {data.get('status', str(data))}"

    # help
    if lower in ("help", "?", "h"):
        return (
            "*SOVEREIGN Commands*\n"
            "• `status` — agent health and recent events\n"
            "• `task <description>` — dispatch a task\n"
            "• `plan <goal>` — decompose a goal into steps\n"
            "• `ask <prompt>` — reason via MetaClaw\n"
            "• `chat <message>` — talk to SOVEREIGN directly\n"
            "• `diagnose <component> <symptoms>` — SRE diagnosis\n"
            "• `recover <agent>` — recovery plan for an agent\n"
            "• `tasks` — show recent task queue\n"
            "• `memory` — show memory store\n"
            "• `events` — show event log\n"
            "• `briefing` — get system briefing\n"
            "• `clear` — clear conversation history\n"
            "• `help` — this message"
        )

    # Fallback: treat as a chat message to SOVEREIGN
    data = sovereign("/chat", method="POST", body={"message": text}, timeout=120)
    if "error" in data:
        return f"❓ Unknown command. Try `help`. (Error: {data['error']})"
    return data.get("response", "❓ Unknown command. Try `help`.")

# ── Event Handlers ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say, logger):
    raw  = event.get("text", "")
    text = raw.split(">", 1)[-1].strip() if ">" in raw else raw.strip()
    user = event.get("user", "?")
    ts   = event.get("ts")
    channel = event.get("channel")

    log.info("Mention from %s: %s", user, text[:80])

    if not text:
        say(text="I'm here, Sirach. Type `help` to see what I can do.", thread_ts=ts)
        return

    reply = dispatch(text)
    say(text=reply, thread_ts=ts)


@app.event("message")
def handle_dm(event, say, logger):
    # Only respond to direct messages (channel_type = im), not channel messages
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id"):
        return

    text = event.get("text", "").strip()
    user = event.get("user", "?")
    log.info("DM from %s: %s", user, text[:80])

    if not text:
        return

    reply = dispatch(text)
    say(text=reply)


@app.command("/sovereign")
def handle_slash(ack, respond, command):
    ack()
    text  = command.get("text", "").strip()
    log.info("Slash command: %s", text[:80])
    reply = dispatch(text or "status")
    respond(text=reply)

# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("SOVEREIGN Slack Bot starting (Socket Mode)")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
