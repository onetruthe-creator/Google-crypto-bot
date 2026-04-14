#!/usr/bin/env python3
"""Slack → MetaClaw → ZeroClaw bridge (socket mode)

Flow:
  Slack DM/mention
    → MetaClaw safety pre-check (financial kill switch)
    → if approved: ZeroClaw agent (136 skills, uses MetaClaw as LLM backend)
    → response back to Slack

Setup:
  pip install slack-bolt slack-sdk httpx

Environment variables:
  SLACK_BOT_TOKEN   xoxb-...
  SLACK_APP_TOKEN   xapp-...
"""

import os
import glob
import logging
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "xoxb-REPLACE_ME")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "xapp-REPLACE_ME")
METACLAW_URL    = "http://127.0.0.1:11434/v1/chat/completions"
MODEL           = "llama3.2:1b"
METACLAW_BASE   = "http://127.0.0.1:30000/v1"
ZEROCLAW_BIN     = os.path.expanduser("~/.cargo/bin/zeroclaw")
SKILLS_DIR       = os.path.expanduser("~/.zeroclaw/workspace/skills")
ZEROCLAW_WEBHOOK = "http://127.0.0.1:3001/webhook"
ZEROCLAW_TOKEN   = os.environ.get("ZEROCLAW_TOKEN", "")
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_skills() -> list[str]:
    paths = glob.glob(os.path.join(SKILLS_DIR, "*/SKILL.md"))
    return sorted(os.path.basename(os.path.dirname(p)) for p in paths)


_BLOCK_KEYWORDS = [
    "send eth", "send btc", "send crypto", "send funds", "send money",
    "transfer eth", "transfer btc", "transfer crypto", "transfer funds",
    "withdraw", "wire transfer", "send coin", "send token",
    "move funds", "move crypto", "pay with crypto",
    "send usdt", "send usdc", "send sol", "send bnb",
    "transfer usdt", "transfer usdc", "transfer sol",
]

def metaclaw_safety_check(user_msg: str) -> tuple[bool, str]:
    """
    Instant keyword-only kill switch — no LLM call, no latency.
    Blocks explicit financial transfer requests immediately.
    """
    lower = user_msg.lower()
    for kw in _BLOCK_KEYWORDS:
        if kw in lower:
            log.warning(f"[KEYWORD BLOCK] matched '{kw}'")
            return False, "MetaClaw financial kill switch activated. Transaction blocked."
    return True, "APPROVED"


def run_zeroclaw(user_msg: str) -> str:
    """
    Send message to ZeroClaw gateway webhook.
    Gateway runs the agent with installed skills and ollama as LLM backend.
    """
    try:
        headers = {}
        if ZEROCLAW_TOKEN:
            headers["Authorization"] = f"Bearer {ZEROCLAW_TOKEN}"
        with httpx.Client(timeout=55) as client:
            resp = client.post(ZEROCLAW_WEBHOOK, json={"message": user_msg}, headers=headers)
            resp.raise_for_status()
            # Webhook may return plain text or JSON
            try:
                data = resp.json()
                # Handle ZeroClaw {"model":..., "response":...} and other formats
                return (
                    data.get("response")
                    or data.get("reply")
                    or data.get("message")
                    or data.get("content")
                    or str(data)
                )
            except Exception:
                return resp.text.strip() or "No response."
    except httpx.HTTPStatusError as e:
        log.warning(f"Webhook HTTP error {e.response.status_code}, falling back to MetaClaw")
        return ask_metaclaw_direct(user_msg)
    except Exception as e:
        log.warning(f"Webhook error: {e}, falling back to MetaClaw")
        return ask_metaclaw_direct(user_msg)


def ask_metaclaw_direct(user_msg: str) -> str:
    """Fallback: send directly to MetaClaw if ZeroClaw binary not found."""
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(METACLAW_URL, json={
                "model": MODEL,
                "messages": [{"role": "user", "content": user_msg}],
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"MetaClaw error: {e}"


def pipeline(user_msg: str) -> str:
    """Full pipeline: MetaClaw safety check → ZeroClaw agent → response."""
    # Step 1: MetaClaw kill switch
    allowed, verdict = metaclaw_safety_check(user_msg)
    if not allowed:
        log.warning(f"[BLOCKED] {user_msg[:80]}")
        return f"🛑 {verdict}"

    # Step 2: ZeroClaw agent with skills
    log.info(f"[APPROVED] routing to ZeroClaw: {user_msg[:80]}")
    return run_zeroclaw(user_msg)


# ── Slack handlers ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    if "<@" in text:
        text = text.split(">", 1)[-1].strip()

    if text.lower().strip() == "skills":
        skills = list_skills()
        say(f"{len(skills)} skills installed: {', '.join(skills)}")
        return

    log.info(f"[mention] {text[:120]}")
    say("⏳ Processing...")
    say(pipeline(text))


@app.event("message")
def handle_dm(event, say):
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("channel_type") != "im":
        return

    text = event.get("text", "").strip()
    if not text:
        return

    if text.lower().strip() == "skills":
        skills = list_skills()
        say(f"{len(skills)} skills installed:\n" + "\n".join(f"• {s}" for s in skills))
        return

    log.info(f"[dm] {text[:120]}")
    say("⏳ Processing...")
    say(pipeline(text))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "REPLACE_ME" in SLACK_BOT_TOKEN or "REPLACE_ME" in SLACK_APP_TOKEN:
        print("ERROR: Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN before running.")
        print("  export SLACK_BOT_TOKEN=xoxb-...")
        print("  export SLACK_APP_TOKEN=xapp-...")
        raise SystemExit(1)

    skills = list_skills()
    zc_status = "found" if os.path.isfile(ZEROCLAW_BIN) else "NOT FOUND (falling back to MetaClaw)"
    print(f"ZeroClaw binary: {zc_status}")
    print(f"Skills loaded:   {len(skills)}")
    print(f"Pipeline:        Slack → MetaClaw (safety) → ZeroClaw (agent) → Slack")
    print("Slack bridge starting (socket mode)...")

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
