#!/usr/bin/env python3
"""Slack → MetaClaw → ZeroClaw bridge (socket mode)

Flow:
  Slack DM/mention
    → MetaClaw safety pre-check (financial kill switch)
    → if approved: MaxMillion pre-dispatch (trade/metrics intent detected)
        → ZeroClaw agent narrates the MaxMillion result
      else (no trade intent):
        → ZeroClaw agent handles normally
    → response back to Slack

Setup:
  pip install slack-bolt slack-sdk httpx

Environment variables:
  SLACK_BOT_TOKEN   xoxb-...
  SLACK_APP_TOKEN   xapp-...
"""

import os
import re
import glob
import logging
import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Memory + tool imports ─────────────────────────────────────────────────────
# Import gracefully so the bridge still starts even if memory.py has a
# transient error (e.g. disk full).  Both modules live in the same folder.
try:
    from memory import mem as _mem
    _MEMORY_OK = True
except Exception as _mem_err:
    logging.getLogger(__name__).warning(
        f"[memory] could not import memory module: {_mem_err}"
    )
    _mem    = None
    _MEMORY_OK = False

try:
    from tools import extract_and_run_tool_from_text as _extract_tool
    _TOOLS_OK = True
except Exception as _tools_err:
    logging.getLogger(__name__).warning(
        f"[tools] could not import tools module: {_tools_err}"
    )
    _extract_tool = None
    _TOOLS_OK = False

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN  = os.environ.get("SLACK_BOT_TOKEN", "xoxb-REPLACE_ME")
SLACK_APP_TOKEN  = os.environ.get("SLACK_APP_TOKEN", "xapp-REPLACE_ME")
METACLAW_URL     = "http://127.0.0.1:11434/v1/chat/completions"
MODEL            = "zeroclaw:latest"
METACLAW_BASE    = "http://127.0.0.1:30000/v1"
ZEROCLAW_BIN     = os.path.expanduser("~/.cargo/bin/zeroclaw")
SKILLS_DIR       = os.path.expanduser("~/.zeroclaw/workspace/skills")
ZEROCLAW_WEBHOOK = "http://127.0.0.1:42617/webhook"
ZEROCLAW_TOKEN   = os.environ.get("ZEROCLAW_TOKEN", "")
MAXMILLION_URL   = os.environ.get("MAXMILLION_URL", "http://127.0.0.1:8082")
PLANDEX_URL      = os.environ.get("PLANDEX_URL", "http://10.0.0.144:8090/ask")
LEGAL_AGENT_URL   = os.environ.get("LEGAL_AGENT_URL",   "http://127.0.0.1:8086")
VOLTAGE_AGENT_URL = os.environ.get("VOLTAGE_AGENT_URL", "http://127.0.0.1:8088")
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
app = App(token=SLACK_BOT_TOKEN)


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_skills() -> list[str]:
    paths = glob.glob(os.path.join(SKILLS_DIR, "*/SKILL.md"))
    return sorted(os.path.basename(os.path.dirname(p)) for p in paths)


# ── MaxMillion intent detection ───────────────────────────────────────────────

# Symbols supported by MaxMillion (SKILL.md canonical list)
_SUPPORTED_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "DOGE"]

# Maps intent keywords → action
_TRADE_PATTERNS = [
    (re.compile(r'\b(trade|buy|sell|execute|place.{0,10}trade|short|long)\b', re.I), "trade"),
]
_METRICS_PATTERNS = [
    (re.compile(r'\b(balance|portfolio|pnl|p&l|profit|loss|metrics|snapshot|daily.trades|how.am.i.doing)\b', re.I), "metrics"),
]
_HEALTH_PATTERNS = [
    (re.compile(r'\b(health|alive|status|up|ping|maxmillion)\b', re.I), "health"),
]


def _extract_symbol(text: str) -> str:
    """Return the first recognised trading symbol found in text, defaulting to BTC/USDT."""
    upper = text.upper()
    for sym in _SUPPORTED_SYMBOLS:
        # Match bare symbol (BTC) or pair (BTC/USDT, BTCUSDT)
        if re.search(rf'\b{sym}\b', upper):
            return f"{sym}/USDT"
    return "BTC/USDT"


def _detect_maxmillion_intent(text: str) -> str | None:
    """
    Returns 'trade', 'metrics', or 'health' when the message targets MaxMillion,
    else None (message goes straight to ZeroClaw without pre-dispatch).
    """
    for pattern, intent in _TRADE_PATTERNS:
        if pattern.search(text):
            return intent
    for pattern, intent in _METRICS_PATTERNS:
        if pattern.search(text):
            return intent
    for pattern, intent in _HEALTH_PATTERNS:
        if pattern.search(text):
            return intent
    return None


def call_maxmillion(intent: str, user_msg: str) -> dict:
    """
    Dispatch to MaxMillion based on detected intent.
    Returns a dict that is injected into the ZeroClaw prompt so the LLM
    narrates real API data instead of hallucinating.

    Raises on network / HTTP errors (caller handles gracefully).
    """
    with httpx.Client(timeout=10) as client:
        if intent == "trade":
            symbol = _extract_symbol(user_msg)
            log.info(f"[MaxMillion] POST /webhook symbol={symbol}")
            resp = client.post(f"{MAXMILLION_URL}/webhook", json={"symbol": symbol})
            resp.raise_for_status()
            return {"intent": "trade", "symbol": symbol, "result": resp.json()}

        elif intent == "metrics":
            log.info("[MaxMillion] GET /metrics")
            resp = client.get(f"{MAXMILLION_URL}/metrics")
            resp.raise_for_status()
            return {"intent": "metrics", "result": resp.json()}

        elif intent == "health":
            log.info("[MaxMillion] GET /health")
            resp = client.get(f"{MAXMILLION_URL}/health")
            resp.raise_for_status()
            return {"intent": "health", "result": resp.json()}

    return {}


def build_enriched_prompt(user_msg: str, mm_data: dict) -> str:
    """
    Wrap the original user message with MaxMillion API data so ZeroClaw's LLM
    narrates real numbers.  The SKILL.md instructs ZeroClaw never to invent data;
    this guarantees it has real data to work with.
    """
    import json
    intent = mm_data.get("intent", "unknown")
    result = mm_data.get("result", {})

    if intent == "trade":
        symbol = mm_data.get("symbol", "BTC/USDT")
        data_block = (
            f"MaxMillion API response for trade on {symbol}:\n"
            f"{json.dumps(result, indent=2)}"
        )
    elif intent == "metrics":
        data_block = (
            f"MaxMillion API response for portfolio metrics:\n"
            f"{json.dumps(result, indent=2)}"
        )
    elif intent == "health":
        data_block = (
            f"MaxMillion API health response:\n"
            f"{json.dumps(result, indent=2)}"
        )
    else:
        data_block = f"MaxMillion API data:\n{json.dumps(result, indent=2)}"

    return (
        f"[MAXMILLION_DATA]\n{data_block}\n[/MAXMILLION_DATA]\n\n"
        f"User request: {user_msg}\n\n"
        "Use the MAXMILLION_DATA above to answer the user accurately. "
        "Do not invent any numbers. Format your response using the maxmillion-trader skill template."
    )


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
                if "error" in data:
                    log.warning(f"ZeroClaw error response: {data['error']}, falling back to Ollama")
                    return ask_metaclaw_direct(user_msg)
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
        log.warning(f"Webhook HTTP error {e.response.status_code}, falling back to Ollama")
        return ask_metaclaw_direct(user_msg)
    except Exception as e:
        log.warning(f"Webhook error: {e}, falling back to Ollama")
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


def ask_tax(user_msg: str) -> str:
    """Forward tax question to Skyp Tax Agent."""
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(f"{os.environ.get('TAX_AGENT_URL', 'http://127.0.0.1:8087')}/ask",
                               json={"question": user_msg})
            resp.raise_for_status()
            return resp.json().get("response") or "No response from tax agent."
    except Exception as e:
        log.warning(f"[Tax] unreachable: {e}")
        return f"Tax agent unreachable: {e}"


def ask_plandex(user_msg: str) -> str:
    """Forward message to Plandex on Raspberry Pi."""
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(PLANDEX_URL, json={"message": user_msg})
            resp.raise_for_status()
            return resp.json().get("response") or resp.text.strip() or "No response from Plandex."
    except Exception as e:
        log.warning(f"[Plandex] unreachable: {e}")
        return f"Plandex (Pi) is unreachable: {e}"


def ask_legal(user_msg: str) -> str:
    """Forward legal question to Skyp_the_Bot legal agent."""
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(f"{LEGAL_AGENT_URL}/ask", json={"question": user_msg})
            resp.raise_for_status()
            data = resp.json()
            return data.get("answer") or data.get("response") or "No response from legal agent."
    except Exception as e:
        log.warning(f"[Legal] unreachable: {e}")
        return f"Legal agent (Skyp_the_Bot) is unreachable: {e}"


def ask_voltage(user_msg: str) -> str:
    """Forward hardware/voltage question to Voltage Agent (Jetson tegrastats)."""
    try:
        with httpx.Client(timeout=30) as client:
            # If no question, just return the live summary
            if not user_msg or user_msg.lower() in ("status", "metrics", "stats"):
                resp = client.get(f"{VOLTAGE_AGENT_URL}/summary")
                resp.raise_for_status()
                return resp.json().get("summary", str(resp.json()))
            resp = client.post(f"{VOLTAGE_AGENT_URL}/ask", json={"question": user_msg})
            resp.raise_for_status()
            data = resp.json()
            return data.get("response") or "No response from voltage agent."
    except Exception as e:
        log.warning(f"[Voltage] unreachable: {e}")
        return f"Voltage agent is unreachable: {e}"


# ── Memory helpers ────────────────────────────────────────────────────────────

def _mem_save(role: str, content: str, channel: str = "") -> None:
    """
    Write one message to the SQLite memory notebook.
    Silently skips if memory is unavailable so the bot never crashes over this.
    """
    if _MEMORY_OK and _mem:
        try:
            _mem.save_message(role, content, channel)
        except Exception as exc:
            log.warning(f"[memory] save_message failed: {exc}")


def _mem_context(channel: str = "", limit: int = 10) -> str:
    """
    Return the last `limit` messages as a compact text block so ZeroClaw
    can see recent context and avoid repeating itself.

    Returns an empty string when memory is unavailable.
    """
    if not (_MEMORY_OK and _mem):
        return ""
    try:
        history = _mem.get_history(limit=limit, channel=channel)
        if not history:
            return ""
        lines = [f"[{m['role']}] {m['content']}" for m in history]
        return "[RECENT_MEMORY]\n" + "\n".join(lines) + "\n[/RECENT_MEMORY]\n\n"
    except Exception as exc:
        log.warning(f"[memory] get_history failed: {exc}")
        return ""


def pipeline(user_msg: str, channel: str = "") -> str:
    """
    Full pipeline:
      Memory save → MetaClaw safety check → MaxMillion pre-dispatch
      → ZeroClaw narration → memory save reply
    """
    # Step 0: Remember what the user said
    _mem_save("user", user_msg, channel)

    # Step 1: MetaClaw kill switch
    allowed, verdict = metaclaw_safety_check(user_msg)
    if not allowed:
        log.warning(f"[BLOCKED] {user_msg[:80]}")
        reply = f"🛑 {verdict}"
        _mem_save("bot", reply, channel)
        return reply

    # Step 1b: prefix routing — "tax:", "legal:", "voltage:", "plandex:" shortcuts
    lower_msg = user_msg.lower()

    if lower_msg.startswith("tax:"):
        query = user_msg[4:].strip()
        log.info(f"[Tax] routing to Skyp Tax Agent: {query[:80]}")
        reply = ask_tax(query)
        _mem_save("bot", reply, channel)
        return reply

    if lower_msg.startswith("legal:"):
        query = user_msg[6:].strip()
        log.info(f"[Legal] routing to Skyp_the_Bot: {query[:80]}")
        reply = ask_legal(query)
        _mem_save("bot", reply, channel)
        return reply

    if lower_msg.startswith("voltage:") or lower_msg.startswith("jetson:"):
        prefix_len = 8 if lower_msg.startswith("voltage:") else 7
        query = user_msg[prefix_len:].strip()
        log.info(f"[Voltage] routing to Voltage Agent: {query[:80]}")
        reply = ask_voltage(query)
        _mem_save("bot", reply, channel)
        return reply

    if lower_msg.startswith("plandex:"):
        query = user_msg[8:].strip()
        log.info(f"[Plandex] routing to Pi: {query[:80]}")
        reply = ask_plandex(query)
        _mem_save("bot", reply, channel)
        return reply

    # Step 2: MaxMillion pre-dispatch — call the real API before ZeroClaw sees the message
    intent = _detect_maxmillion_intent(user_msg)
    # Prepend recent memory context so ZeroClaw remembers the conversation
    context_block  = _mem_context(channel=channel, limit=10)
    prompt_to_zeroclaw = context_block + user_msg  # default: context + user message

    if intent:
        try:
            mm_data = call_maxmillion(intent, user_msg)
            enriched = build_enriched_prompt(user_msg, mm_data)
            prompt_to_zeroclaw = context_block + enriched
            log.info(f"[MaxMillion] pre-dispatch OK intent={intent}")
        except httpx.HTTPStatusError as e:
            log.warning(f"[MaxMillion] HTTP {e.response.status_code} — checking kill switch state")
            # If MaxMillion returns 503 the kill switch is active; surface that clearly
            if e.response.status_code in (503, 423):
                try:
                    ks = e.response.json().get("detail") or e.response.text
                except Exception:
                    ks = str(e)
                reply = f"Trading halted — MaxMillion kill switch is active: {ks}"
                _mem_save("bot", reply, channel)
                return reply
            # Other HTTP errors: fall through to ZeroClaw without pre-dispatch data
            log.warning("[MaxMillion] Falling through to ZeroClaw without pre-dispatch data")
        except Exception as e:
            log.warning(f"[MaxMillion] Unreachable ({e}) — falling through to ZeroClaw")
            # MaxMillion is down: let ZeroClaw respond with an error explanation
            mm_error_block = (
                f"[MAXMILLION_DATA]\nError: MaxMillion trading server is unreachable "
                f"({e}). Do not invent trade data.\n[/MAXMILLION_DATA]\n\n"
                f"User request: {user_msg}"
            )
            prompt_to_zeroclaw = context_block + mm_error_block

    # Step 3: ZeroClaw narrates the result (enriched prompt contains real API data)
    log.info(f"[APPROVED] routing to ZeroClaw intent={intent or 'none'}: {user_msg[:60]}")
    reply = run_zeroclaw(prompt_to_zeroclaw)

    # Step 3b: If ZeroClaw returned a raw tool-call JSON blob, execute it
    if _TOOLS_OK and _extract_tool:
        tool_result = _extract_tool(reply)
        if tool_result:
            log.info("[tools] ZeroClaw returned a tool call — executed and replacing reply")
            reply = tool_result

    # Step 4: Remember the bot's reply
    _mem_save("bot", reply, channel)
    return reply


# ── Slack handlers ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    text    = event.get("text", "")
    channel = event.get("channel", "")
    if "<@" in text:
        text = text.split(">", 1)[-1].strip()

    if text.lower().strip() == "skills":
        skills = list_skills()
        say(f"{len(skills)} skills installed: {', '.join(skills)}")
        return

    log.info(f"[mention] {text[:120]}")
    say("⏳ Processing...")
    say(pipeline(text, channel=channel))


@app.event("message")
def handle_dm(event, say):
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("channel_type") != "im":
        return

    text    = event.get("text", "").strip()
    channel = event.get("channel", "")
    if not text:
        return

    if text.lower().strip() == "skills":
        skills = list_skills()
        say(f"{len(skills)} skills installed:\n" + "\n".join(f"• {s}" for s in skills))
        return

    log.info(f"[dm] {text[:120]}")
    say("⏳ Processing...")
    say(pipeline(text, channel=channel))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "REPLACE_ME" in SLACK_BOT_TOKEN or "REPLACE_ME" in SLACK_APP_TOKEN:
        print("ERROR: Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN before running.")
        print("  export SLACK_BOT_TOKEN=xoxb-...")
        print("  export SLACK_APP_TOKEN=xapp-...")
        raise SystemExit(1)

    skills = list_skills()
    zc_status = "found" if os.path.isfile(ZEROCLAW_BIN) else "NOT FOUND (falling back to MetaClaw)"
    print(f"ZeroClaw binary:  {zc_status}")
    print(f"Skills loaded:    {len(skills)}")
    print(f"MaxMillion URL:   {MAXMILLION_URL}")
    print(f"Pipeline:         Slack → MetaClaw (safety) → MaxMillion (pre-dispatch) → ZeroClaw (narrate) → Slack")
    print("Slack bridge starting (socket mode)...")

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
