#!/usr/bin/env python3
"""Slack → MetaClaw bridge using Slack Bolt (socket mode)

Setup:
  pip install slack-bolt slack-sdk httpx

Slack App Requirements:
  1. Go to https://api.slack.com/apps → Create New App → From scratch
  2. Under "OAuth & Permissions" add Bot Token Scopes:
       app_mentions:read
       channels:history
       chat:write
       im:history
       im:write
       mpim:history
  3. Under "Event Subscriptions" → Enable Events → Subscribe to bot events:
       app_mention
       message.im
  4. Under "Socket Mode" → Enable Socket Mode
  5. Under "Basic Information" → App-Level Tokens → Generate token with:
       connections:write scope  →  this is your SLACK_APP_TOKEN
  6. Install app to workspace → copy "Bot User OAuth Token" → SLACK_BOT_TOKEN
  7. Invite your bot to the channel: /invite @YourBotName

Environment variables (or edit constants below):
  SLACK_BOT_TOKEN   xoxb-...
  SLACK_APP_TOKEN   xapp-...
"""

import os
import glob
import logging
import subprocess
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "xoxb-REPLACE_ME")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "xapp-REPLACE_ME")
METACLAW        = "http://127.0.0.1:30000/v1/chat/completions"
MODEL           = "llama3.2"
ZEROCLAW_BIN    = os.path.expanduser("~/.cargo/bin/zeroclaw")
SKILLS_DIR      = os.path.expanduser("~/.zeroclaw/workspace/skills")
USE_ZEROCLAW    = os.path.isfile(ZEROCLAW_BIN)  # use agent if binary exists
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
app = App(token=SLACK_BOT_TOKEN)


def list_skills() -> str:
    """Return a comma-separated list of installed skill names."""
    dirs = glob.glob(os.path.join(SKILLS_DIR, "*/SKILL.md"))
    names = sorted(os.path.basename(os.path.dirname(p)) for p in dirs)
    return ", ".join(names) if names else "none"


def ask_zeroclaw(user_msg: str) -> str:
    """Run zeroclaw agent and return its reply (uses all installed skills)."""
    try:
        result = subprocess.run(
            [ZEROCLAW_BIN, "agent",
             "--provider", "custom:http://127.0.0.1:30000/v1",
             "--model", MODEL,
             "-m", user_msg],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout.strip()
        return output if output else (result.stderr.strip() or "No response from ZeroClaw.")
    except subprocess.TimeoutExpired:
        return "ZeroClaw timed out."
    except Exception as e:
        return f"Error running ZeroClaw: {e}"


def ask_metaclaw(user_msg: str) -> str:
    """Send message to MetaClaw and return the reply."""
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(METACLAW, json={
                "model": MODEL,
                "messages": [{"role": "user", "content": user_msg}],
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error contacting MetaClaw: {e}"


def respond(user_msg: str) -> str:
    """Route to ZeroClaw agent (with skills) if available, else MetaClaw."""
    if USE_ZEROCLAW:
        return ask_zeroclaw(user_msg)
    return ask_metaclaw(user_msg)


@app.event("app_mention")
def handle_mention(event, say):
    """Reply to @mentions in channels."""
    # Strip the bot mention prefix (<@BOTID> ...)
    text = event.get("text", "")
    # Remove the mention token
    if "<@" in text:
        text = text.split(">", 1)[-1].strip()

    print(f"[mention] {text[:120]}")
    if text.lower().strip() == "skills":
        say(f"Installed skills: {list_skills()}")
        return
    reply = respond(text)
    print(f"[reply]   {reply[:120]}")
    say(reply)


@app.event("message")
def handle_dm(event, say):
    """Reply to direct messages (DMs)."""
    # Ignore bot messages and message subtypes (edits, deletes, etc.)
    if event.get("bot_id") or event.get("subtype"):
        return
    # Only handle DMs (channel_type == "im")
    if event.get("channel_type") != "im":
        return

    text = event.get("text", "").strip()
    if not text:
        return

    print(f"[dm]    {text[:120]}")
    if text.lower().strip() == "skills":
        say(f"Installed skills ({len(glob.glob(os.path.join(SKILLS_DIR, '*/SKILL.md')))}): {list_skills()}")
        return
    reply = respond(text)
    print(f"[reply] {reply[:120]}")
    say(reply)


if __name__ == "__main__":
    if "REPLACE_ME" in SLACK_BOT_TOKEN or "REPLACE_ME" in SLACK_APP_TOKEN:
        print("ERROR: Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN before running.")
        print("  export SLACK_BOT_TOKEN=xoxb-...")
        print("  export SLACK_APP_TOKEN=xapp-...")
        raise SystemExit(1)

    print("Slack bridge starting (socket mode)...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
