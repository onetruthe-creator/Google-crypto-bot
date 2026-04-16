#!/usr/bin/env python3
"""
tools.py — Agent tool registry for the crypto trading bot.

Think of these like apps on a phone.
The bot (ZeroClaw / Ollama) can "call" any tool here to get real data
instead of guessing or making numbers up.

How it works
------------
1. The LLM decides it needs data (e.g. "what is my balance?").
2. It returns a special JSON blob called a "tool call":
       {"tool": "get_balance", "args": {}}
3. Our code here runs the matching function and sends the result back to the LLM.
4. The LLM writes a nice human-readable reply using the real data.

Tools available
---------------
  get_balance       — current cash balance from MaxMillion
  get_portfolio     — full list of coin holdings from MaxMillion
  get_trade_history — recent trades from our SQLite memory
  get_chat_history  — recent Slack messages from our SQLite memory
  get_trade_summary — win/loss stats across all recorded trades
  search_memory     — search past conversations for a keyword

Usage (from another script)
----------------------------
  from tools import call_tool, TOOL_SCHEMAS

  # Ask the LLM to use tools by including TOOL_SCHEMAS in your prompt.
  # When the LLM returns a tool call JSON, run it like this:
  result = call_tool("get_balance", {})
  print(result)   # {"balance": 10042.00, "currency": "USDT", ...}
"""

import json
import logging
import httpx
from memory import mem   # our SQLite notebook (memory.py must be in the same folder)

log = logging.getLogger(__name__)

# ── Service URLs ──────────────────────────────────────────────────────────────
# These match the ports described in the project README.
MAXMILLION_URL = "http://127.0.0.1:8082"   # mock trading server
ZEROCLAW_URL   = "http://127.0.0.1:42617"  # ZeroClaw AI gateway
OLLAMA_URL     = "http://127.0.0.1:11434"  # local LLM


# ── Tool schemas ──────────────────────────────────────────────────────────────
# This list tells the LLM what tools exist and what each one does.
# It follows the OpenAI "function calling" format so ZeroClaw / Ollama
# can understand it directly.

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": (
                "Get the current cash balance from MaxMillion mock trading. "
                "Call this when the user asks how much money they have."
            ),
            "parameters": {
                "type": "object",
                "properties": {},   # no input needed
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": (
                "Get the full list of coin holdings (symbol, quantity, value) "
                "from MaxMillion. Call this when the user asks about their portfolio "
                "or what coins they own."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trade_history",
            "description": (
                "Get the most recent trades from the bot's memory (SQLite). "
                "Includes symbol, side (buy/sell), price, quantity, and PnL per trade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many recent trades to return. Default is 10.",
                    },
                    "symbol": {
                        "type": "string",
                        "description": (
                            "Filter to a specific coin pair, e.g. 'BTC/USDT'. "
                            "Leave empty to get all symbols."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_history",
            "description": (
                "Get the most recent Slack messages the bot has seen or sent. "
                "Use this to remember what was said earlier in the conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many recent messages to return. Default is 10.",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Slack channel ID to filter by. Leave empty for all channels.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trade_summary",
            "description": (
                "Get overall trading stats: total trades, total PnL, win count, "
                "loss count, and latest balance. Great for 'how am I doing?' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Search past Slack conversations for a keyword or phrase. "
                "Use this when the user references something from an earlier chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Word or phrase to search for in past messages.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of matching messages to return. Default is 5.",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
]


# ── Tool functions ────────────────────────────────────────────────────────────
# Each function does one job and returns a plain dict.
# If something goes wrong, it returns {"error": "..."} instead of crashing.

def get_balance(_args: dict = None) -> dict:
    """
    Fetch the current USD/USDT balance from MaxMillion.

    MaxMillion returns something like:
      {"balance": 10042.00, "currency": "USDT"}
    """
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"{MAXMILLION_URL}/metrics")
            resp.raise_for_status()
            data = resp.json()

        # MaxMillion /metrics returns different shapes depending on version.
        # We try a few common field names so it works with any response.
        balance = (
            data.get("balance")
            or data.get("cash_balance")
            or data.get("usdt_balance")
            or data.get("account_balance")
        )

        # If /metrics doesn't have a balance field, check /health as a fallback
        if balance is None:
            resp2 = httpx.get(f"{MAXMILLION_URL}/health", timeout=5)
            if resp2.status_code == 200:
                data2 = resp2.json()
                balance = data2.get("balance") or data2.get("cash")

        return {
            "balance":  round(float(balance), 2) if balance is not None else None,
            "currency": data.get("currency", "USDT"),
            "source":   "maxmillion",
            "raw":      data,
        }
    except httpx.ConnectError:
        # MaxMillion is not running — fall back to the last known balance from memory
        last = mem.get_latest_balance()
        return {
            "balance":  last,
            "currency": "USDT",
            "source":   "memory_fallback",
            "warning":  "MaxMillion is offline. Showing last known balance from trade history.",
        }
    except Exception as exc:
        log.warning(f"[get_balance] error: {exc}")
        return {"error": str(exc), "source": "maxmillion"}


def get_portfolio(_args: dict = None) -> dict:
    """
    Fetch the full portfolio (all coin holdings) from MaxMillion.
    """
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"{MAXMILLION_URL}/metrics")
            resp.raise_for_status()
            data = resp.json()

        # Extract holdings — MaxMillion may call this field different things
        holdings = (
            data.get("holdings")
            or data.get("portfolio")
            or data.get("positions")
            or []
        )

        # If the metrics endpoint doesn't include holdings, build a summary
        # from our trade history so the LLM always has something to work with
        if not holdings:
            trades = mem.get_trades(limit=50)
            # Count net position per symbol
            positions: dict[str, dict] = {}
            for t in trades:
                sym = t["symbol"]
                if sym not in positions:
                    positions[sym] = {"symbol": sym, "net_qty": 0.0, "last_price": 0.0}
                delta = t["qty"] if t["side"] == "buy" else -t["qty"]
                positions[sym]["net_qty"]    += delta
                positions[sym]["last_price"]  = t["fill_price"]
            holdings = [p for p in positions.values() if p["net_qty"] != 0]

        return {
            "holdings": holdings,
            "count":    len(holdings),
            "source":   "maxmillion",
            "raw":      data,
        }
    except httpx.ConnectError:
        # Build a rough picture from memory when MaxMillion is offline
        trades = mem.get_trades(limit=50)
        positions: dict[str, dict] = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in positions:
                positions[sym] = {"symbol": sym, "net_qty": 0.0, "last_price": 0.0}
            delta = t["qty"] if t["side"] == "buy" else -t["qty"]
            positions[sym]["net_qty"]    += delta
            positions[sym]["last_price"]  = t["fill_price"]
        holdings = [p for p in positions.values() if p["net_qty"] != 0]
        return {
            "holdings": holdings,
            "count":    len(holdings),
            "source":   "memory_fallback",
            "warning":  "MaxMillion is offline. Showing estimated positions from trade history.",
        }
    except Exception as exc:
        log.warning(f"[get_portfolio] error: {exc}")
        return {"error": str(exc), "source": "maxmillion"}


def get_trade_history(args: dict = None) -> dict:
    """
    Return recent trades from the SQLite memory database.
    """
    args = args or {}
    limit  = int(args.get("limit", 10))
    symbol = str(args.get("symbol", "")).strip()

    trades = mem.get_trades(limit=limit, symbol=symbol)

    # Add a human-readable label to each trade for the LLM
    for t in trades:
        sign = "+" if t["pnl_tick"] >= 0 else ""
        t["label"] = (
            f"{t['side'].upper()} {t['qty']} {t['symbol']} "
            f"@ ${t['fill_price']:,.2f}  PnL: {sign}{t['pnl_tick']}"
        )

    return {
        "trades":       trades,
        "count":        len(trades),
        "filter_symbol": symbol or "all",
        "source":       "memory",
    }


def get_chat_history(args: dict = None) -> dict:
    """
    Return recent Slack messages from the SQLite memory database.
    """
    args    = args or {}
    limit   = int(args.get("limit", 10))
    channel = str(args.get("channel", "")).strip()

    messages = mem.get_history(limit=limit, channel=channel)

    return {
        "messages": messages,
        "count":    len(messages),
        "source":   "memory",
    }


def get_trade_summary(_args: dict = None) -> dict:
    """
    Return aggregate win/loss stats from the SQLite memory database.
    """
    summary = mem.get_trade_summary()
    # Add a quick win-rate percentage so the LLM can quote it easily
    total = summary["total_trades"]
    if total > 0:
        summary["win_rate_pct"] = round(summary["win_count"] / total * 100, 1)
    else:
        summary["win_rate_pct"] = 0.0
    summary["source"] = "memory"
    return summary


def search_memory(args: dict = None) -> dict:
    """
    Full-text search across past Slack messages stored in SQLite.
    """
    args    = args or {}
    keyword = str(args.get("keyword", "")).strip()
    limit   = int(args.get("limit", 5))

    if not keyword:
        return {"error": "keyword is required", "results": []}

    results = mem.search_messages(keyword=keyword, limit=limit)
    return {
        "keyword": keyword,
        "results": results,
        "count":   len(results),
        "source":  "memory",
    }


# ── Tool registry ─────────────────────────────────────────────────────────────
# Maps tool name → function.  Add new tools here.

_REGISTRY: dict[str, callable] = {
    "get_balance":       get_balance,
    "get_portfolio":     get_portfolio,
    "get_trade_history": get_trade_history,
    "get_chat_history":  get_chat_history,
    "get_trade_summary": get_trade_summary,
    "search_memory":     search_memory,
}


def call_tool(name: str, args: dict = None) -> dict:
    """
    Look up a tool by name and run it with the given arguments.

    Parameters
    ----------
    name : exact tool name, e.g. "get_balance"
    args : dict of keyword arguments for the tool (can be empty / None)

    Returns a dict with the tool's result, or {"error": "..."} if unknown.

    Example
    -------
    result = call_tool("get_trade_history", {"limit": 5})
    print(result["trades"])
    """
    if name not in _REGISTRY:
        available = list(_REGISTRY.keys())
        log.warning(f"[call_tool] unknown tool: {name!r}. Available: {available}")
        return {"error": f"Unknown tool: {name!r}", "available_tools": available}

    log.info(f"[call_tool] running: {name}  args={args or {}}")
    try:
        return _REGISTRY[name](args or {})
    except Exception as exc:
        log.error(f"[call_tool] {name} raised: {exc}")
        return {"error": f"Tool {name!r} failed: {exc}"}


def list_tools() -> list[str]:
    """Return the names of all registered tools."""
    return list(_REGISTRY.keys())


# ── Ollama tool-call loop helper ──────────────────────────────────────────────

def run_with_tools(
    user_message: str,
    system_prompt: str = "",
    chat_history: list[dict] | None = None,
    model: str = "llama3.2:1b",
    max_tool_rounds: int = 3,
) -> str:
    """
    Send a message to Ollama, let it call tools up to `max_tool_rounds` times,
    then return the final text answer.

    This is the main "agent loop":
      1. Send message + tool schemas to Ollama.
      2. If Ollama returns a tool_call, run the tool, send the result back.
      3. Repeat until Ollama gives a plain text reply (or we hit the round limit).

    Parameters
    ----------
    user_message    : the user's question or request
    system_prompt   : instructions for the LLM (optional)
    chat_history    : previous messages in OpenAI format (optional)
    model           : Ollama model name (default: llama3.2:1b)
    max_tool_rounds : safety limit — how many tool calls allowed per reply

    Returns the final plain-text answer from the LLM.

    Example
    -------
    answer = run_with_tools("What is my current balance?")
    print(answer)
    """
    # Build the message list: system prompt + history + new user message
    messages: list[dict] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if chat_history:
        messages.extend(chat_history)

    messages.append({"role": "user", "content": user_message})

    for round_num in range(max_tool_rounds + 1):
        # ── Call Ollama ───────────────────────────────────────────────────────
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{OLLAMA_URL}/v1/chat/completions",
                    json={
                        "model":   model,
                        "messages": messages,
                        "tools":   TOOL_SCHEMAS,   # tell Ollama what tools exist
                        "stream":  False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.error(f"[run_with_tools] Ollama error: {exc}")
            return f"I had trouble reaching the AI model: {exc}"

        choice  = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish  = choice.get("finish_reason", "stop")

        # ── Plain text reply — we're done ─────────────────────────────────────
        if finish == "stop" or not message.get("tool_calls"):
            return message.get("content") or "I have no answer right now."

        # ── Tool call requested ───────────────────────────────────────────────
        if round_num >= max_tool_rounds:
            # We've hit the limit; ask Ollama to summarise without more tools
            log.warning("[run_with_tools] hit max_tool_rounds, forcing final answer")
            messages.append({"role": "assistant", "content": json.dumps(message)})
            messages.append({
                "role":    "user",
                "content": "Please summarise what you know and give a final answer now.",
            })
            continue

        tool_calls = message.get("tool_calls", [])
        # Add the assistant's tool-call turn to the message history
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})

        # Run each requested tool and add the results back
        for tc in tool_calls:
            tc_id   = tc.get("id", "call_0")
            fn      = tc.get("function", {})
            name    = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            log.info(f"[run_with_tools] round {round_num+1}: tool={name} args={args}")
            result = call_tool(name, args)

            messages.append({
                "role":         "tool",
                "tool_call_id": tc_id,
                "content":      json.dumps(result),
            })

    return "I was unable to produce a final answer within the tool call limit."


# ── Simple JSON tool-call parser (for ZeroClaw text responses) ─────────────────
# ZeroClaw sometimes returns tool calls as a raw JSON string in its text response
# rather than in the OpenAI tool_calls field.  This helper catches that case.

def extract_and_run_tool_from_text(text: str) -> str | None:
    """
    Check if `text` contains a JSON tool-call blob like:
        {"tool": "get_balance", "args": {}}
    or:
        {"tool_call": {"name": "get_balance", "arguments": {}}}

    If found, runs the tool and returns a formatted result string.
    Returns None if no tool call is detected (the text is just a normal reply).

    Example
    -------
    reply = '{"tool": "get_balance", "args": {}}'
    result_text = extract_and_run_tool_from_text(reply)
    if result_text:
        print(result_text)   # "Balance: $10,042.00 USDT"
    else:
        print(reply)          # it was a normal reply, print as-is
    """
    text = text.strip()

    # Only bother trying if the text looks like JSON
    if not (text.startswith("{") or "tool" in text.lower()):
        return None

    # Try to pull out the first JSON object from the text
    try:
        start = text.index("{")
        end   = text.rindex("}") + 1
        blob  = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None

    # Pattern 1: {"tool": "get_balance", "args": {...}}
    if "tool" in blob and isinstance(blob["tool"], str):
        name = blob["tool"]
        args = blob.get("args") or blob.get("arguments") or {}
        result = call_tool(name, args)
        return f"[Tool: {name}]\n{json.dumps(result, indent=2)}"

    # Pattern 2: {"tool_call": {"name": "get_balance", "arguments": {...}}}
    if "tool_call" in blob and isinstance(blob["tool_call"], dict):
        inner = blob["tool_call"]
        name  = inner.get("name", "")
        args  = inner.get("arguments") or {}
        result = call_tool(name, args)
        return f"[Tool: {name}]\n{json.dumps(result, indent=2)}"

    return None


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Tool Registry Self-Test ===\n")
    print(f"Registered tools: {list_tools()}\n")

    # Test every tool that only needs memory (no live server needed)
    print("--- get_trade_history (from memory) ---")
    r = call_tool("get_trade_history", {"limit": 3})
    print(json.dumps(r, indent=2))

    print("\n--- get_chat_history (from memory) ---")
    r = call_tool("get_chat_history", {"limit": 3})
    print(json.dumps(r, indent=2))

    print("\n--- get_trade_summary (from memory) ---")
    r = call_tool("get_trade_summary", {})
    print(json.dumps(r, indent=2))

    print("\n--- search_memory: 'balance' ---")
    r = call_tool("search_memory", {"keyword": "balance", "limit": 2})
    print(json.dumps(r, indent=2))

    print("\n--- get_balance (tries MaxMillion, falls back to memory if offline) ---")
    r = call_tool("get_balance", {})
    print(json.dumps(r, indent=2))

    print("\n--- get_portfolio (tries MaxMillion, falls back to memory if offline) ---")
    r = call_tool("get_portfolio", {})
    print(json.dumps(r, indent=2))

    print("\n--- extract_and_run_tool_from_text ---")
    text_blob = '{"tool": "get_trade_summary", "args": {}}'
    result = extract_and_run_tool_from_text(text_blob)
    print(result)

    print("\nSelf-test complete.")
