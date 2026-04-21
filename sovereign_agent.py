#!/usr/bin/env python3
"""
Sovereign Agent — Autonomous Master Orchestrator (port 8090)

The top-level brain that:
  1. Routes any complex request to the right agent(s) and synthesizes results
  2. Runs background autonomous loops — monitors hardware, portfolio, and all agents
  3. Proactively pushes Slack alerts without being asked
  4. Chains multiple agents together for deep analysis

Autonomous monitors (run forever in background):
  - Every 60s  : health-check all agents, alert if any go down
  - Every 5min : Jetson hardware (temp, RAM, power) — alert if critical
  - Every 30min: Portfolio snapshot from MaxMillion + Sheets
  - Every 6hr  : Tax estimate based on current PnL
  - Every 24hr : Full system digest pushed to Slack

Endpoints:
  GET  /health          — service check + all-agent status
  GET  /status          — full system snapshot
  POST /ask             — intelligent multi-agent query
  POST /chain           — explicit agent chain: [{agent, query}, ...]
  GET  /agents          — list all known agents and their status

systemd service (Jetson terminal):
  sudo tee /etc/systemd/system/sovereign.service > /dev/null << 'EOF'
  [Unit]
  Description=Sovereign Agent - Autonomous Master Orchestrator
  After=network.target
  [Service]
  Type=simple
  User=damon
  WorkingDirectory=/home/damon/maxmillion
  ExecStart=/home/damon/maxmillion/venv/bin/python sovereign_agent.py
  Restart=always
  RestartSec=10
  Environment=SLACK_BOT_TOKEN=REPLACE_ME
  Environment=SLACK_CHANNEL=REPLACE_ME
  [Install]
  WantedBy=multi-user.target
  EOF
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
PORT              = 8090
SLACK_BOT_TOKEN   = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL     = os.environ.get("SLACK_CHANNEL", "")    # e.g. C08XXXXXXXX

# Agent registry — name: base URL
AGENTS = {
    "maxmillion":          "http://127.0.0.1:8082",
    "sheets":              "http://127.0.0.1:8083",
    "tradingview":         "http://127.0.0.1:8085",
    "legal":               "http://127.0.0.1:8086",
    "tax":                 "http://127.0.0.1:8087",
    "voltage":             "http://127.0.0.1:8088",
    "skill_router":        "http://127.0.0.1:8089",
}

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL      = "zeroclaw:latest"

# Autonomous monitor intervals (seconds)
HEALTH_INTERVAL     = 60
HARDWARE_INTERVAL   = 300
PORTFOLIO_INTERVAL  = 1800
TAX_INTERVAL        = 21600
DIGEST_INTERVAL     = 86400

# Alert thresholds
TEMP_WARN_C   = 70.0
RAM_WARN_PCT  = 85.0
POWER_WARN_W  = 10.0
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [sovereign] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Sovereign Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── State ─────────────────────────────────────────────────────────────────────
_agent_status: dict[str, str] = {k: "unknown" for k in AGENTS}
_last_portfolio: dict         = {}
_last_hardware: dict          = {}
_alerts_sent: set[str]        = set()   # deduplicate alerts


# ── Slack helper ──────────────────────────────────────────────────────────────

async def slack_send(text: str, channel: str = "") -> bool:
    """Push a message to Slack. Returns True on success."""
    ch = channel or SLACK_CHANNEL
    if not SLACK_BOT_TOKEN or not ch:
        log.warning("[Slack] token or channel not configured — skipping alert")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": ch, "text": text},
            )
            data = resp.json()
            if not data.get("ok"):
                log.warning(f"[Slack] API error: {data.get('error')}")
                return False
            return True
    except Exception as e:
        log.warning(f"[Slack] send failed: {e}")
        return False


# ── Agent call helpers ────────────────────────────────────────────────────────

async def _get(url: str, timeout: int = 8) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def _post(url: str, body: dict, timeout: int = 90) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json()


async def _agent_health(name: str, base: str) -> str:
    try:
        await _get(f"{base}/health", timeout=5)
        return "up"
    except Exception:
        return "down"


async def check_all_agents() -> dict[str, str]:
    results = await asyncio.gather(
        *[_agent_health(n, u) for n, u in AGENTS.items()],
        return_exceptions=True
    )
    status = {}
    for name, result in zip(AGENTS.keys(), results):
        status[name] = result if isinstance(result, str) else "down"
    return status


# ── Ollama helper ─────────────────────────────────────────────────────────────

async def _ask_ollama(system: str, prompt: str, timeout: int = 90) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":    MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"LLM error: {e}"


# ── Routing intelligence ──────────────────────────────────────────────────────

async def _route(question: str) -> list[str]:
    """Ask the LLM which agents to consult for this question."""
    system = (
        "You are a routing agent. Given a question, output ONLY a comma-separated "
        "list of agent names from this set that should be consulted: "
        "maxmillion, sheets, legal, tax, voltage, skill_router. "
        "No explanation. Just agent names separated by commas."
    )
    raw = await _ask_ollama(system, question, timeout=20)
    agents = [a.strip().lower() for a in raw.split(",")]
    valid  = [a for a in agents if a in AGENTS]
    return valid or ["skill_router"]


async def _call_agent(name: str, question: str) -> str:
    base = AGENTS.get(name, "")
    if not base:
        return f"Unknown agent: {name}"
    try:
        if name == "tax":
            d = await _post(f"{base}/ask", {"question": question})
            return d.get("response", str(d))
        elif name == "legal":
            d = await _post(f"{base}/ask", {"question": question})
            return d.get("answer", str(d))
        elif name == "voltage":
            d = await _post(f"{base}/ask", {"question": question})
            return d.get("response", str(d))
        elif name == "skill_router":
            d = await _post(f"{base}/ask/auto", {"question": question})
            skill = d.get("skill_chosen", "?")
            return f"[{skill}] {d.get('response', str(d))}"
        elif name == "maxmillion":
            d = await _get(f"{base}/metrics")
            return f"MaxMillion metrics: {d}"
        elif name == "sheets":
            d = await _get(f"{base}/summary")
            return f"Portfolio summary: {d}"
        else:
            d = await _get(f"{base}/health")
            return str(d)
    except Exception as e:
        return f"{name} error: {e}"


# ── Autonomous monitors ───────────────────────────────────────────────────────

async def monitor_health():
    """Every 60s — check all agents, alert if any go down or come back up."""
    global _agent_status
    while True:
        await asyncio.sleep(HEALTH_INTERVAL)
        try:
            new_status = await check_all_agents()
            for name, status in new_status.items():
                prev = _agent_status.get(name, "unknown")
                if status == "down" and prev != "down":
                    alert_key = f"down_{name}"
                    if alert_key not in _alerts_sent:
                        _alerts_sent.add(alert_key)
                        msg = f"ALERT: `{name}` agent went DOWN at {datetime.now().strftime('%H:%M:%S')}"
                        log.warning(msg)
                        await slack_send(f"*Sovereign Alert*\n{msg}")
                elif status == "up" and prev == "down":
                    _alerts_sent.discard(f"down_{name}")
                    msg = f"RECOVERED: `{name}` agent is back UP"
                    log.info(msg)
                    await slack_send(f"*Sovereign Alert*\n{msg}")
            _agent_status = new_status
        except Exception as e:
            log.warning(f"[health monitor] error: {e}")


async def monitor_hardware():
    """Every 5min — check Jetson temps, RAM, power and alert if critical."""
    while True:
        await asyncio.sleep(HARDWARE_INTERVAL)
        try:
            global _last_hardware
            d = await _get(f"{AGENTS['voltage']}/metrics")
            _last_hardware = d

            alerts = []
            temp_cpu = d.get("temp_cpu_c", 0)
            temp_gpu = d.get("temp_gpu_c", 0)
            ram_pct  = d.get("ram_pct", 0)
            power_w  = d.get("total_power_w", 0)

            if temp_cpu >= TEMP_WARN_C:
                alerts.append(f"CPU temp {temp_cpu}°C (limit {TEMP_WARN_C}°C)")
            if temp_gpu >= TEMP_WARN_C:
                alerts.append(f"GPU temp {temp_gpu}°C (limit {TEMP_WARN_C}°C)")
            if ram_pct >= RAM_WARN_PCT:
                alerts.append(f"RAM at {ram_pct}% ({d.get('ram_used_mb')}MB used)")
            if power_w >= POWER_WARN_W:
                alerts.append(f"Board power {power_w}W")

            if alerts:
                alert_key = f"hw_{'_'.join(alerts[:1])}"
                if alert_key not in _alerts_sent:
                    _alerts_sent.add(alert_key)
                    msg = "*Sovereign Hardware Alert*\n" + "\n".join(f"• {a}" for a in alerts)
                    await slack_send(msg)
            else:
                # Clear old hardware alerts when back to normal
                _alerts_sent = {k for k in _alerts_sent if not k.startswith("hw_")}

            log.info(f"[hardware] CPU {temp_cpu}°C GPU {temp_gpu}°C RAM {ram_pct}% Power {power_w}W")
        except Exception as e:
            log.warning(f"[hardware monitor] error: {e}")


async def monitor_portfolio():
    """Every 30min — snapshot portfolio, report big PnL changes."""
    while True:
        await asyncio.sleep(PORTFOLIO_INTERVAL)
        try:
            global _last_portfolio
            mm   = await _get(f"{AGENTS['maxmillion']}/metrics")
            prev = _last_portfolio.get("balance", 0)
            curr = mm.get("balance", 0)
            pnl  = mm.get("daily_pnl", 0)

            _last_portfolio = mm

            change_pct = abs((curr - prev) / max(prev, 1)) * 100
            if change_pct >= 5 and prev > 0:
                direction = "UP" if curr > prev else "DOWN"
                msg = (
                    f"*Portfolio {direction} {change_pct:.1f}%*\n"
                    f"Balance: ${curr:,.2f} | Daily PnL: ${pnl:,.2f}"
                )
                await slack_send(msg)

            log.info(f"[portfolio] balance=${curr:,.2f} pnl=${pnl:,.2f}")
        except Exception as e:
            log.warning(f"[portfolio monitor] error: {e}")


async def monitor_tax():
    """Every 6hr — push current tax estimate."""
    while True:
        await asyncio.sleep(TAX_INTERVAL)
        try:
            d   = await _get(f"{AGENTS['tax']}/summary")
            msg = (
                f"*Tax Estimate Update*\n"
                f"Total federal tax: ${d.get('total_federal_tax', 0):,.2f}\n"
                f"Quarterly payment: ${d.get('quarterly_payment', 0):,.2f}\n"
                f"Effective rate: {d.get('effective_rate', 0)}%"
            )
            await slack_send(msg)
            log.info("[tax] estimate pushed to Slack")
        except Exception as e:
            log.warning(f"[tax monitor] error: {e}")


async def daily_digest():
    """Every 24hr — full system status digest."""
    while True:
        await asyncio.sleep(DIGEST_INTERVAL)
        try:
            agent_st = await check_all_agents()
            up_count = sum(1 for s in agent_st.values() if s == "up")

            hw  = _last_hardware
            pf  = _last_portfolio

            lines = [
                f"*Daily Sovereign Digest — {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
                f"Agents: {up_count}/{len(AGENTS)} online",
                "",
            ]
            if hw:
                lines += [
                    "*Jetson Hardware*",
                    f"  CPU {hw.get('temp_cpu_c', '?')}°C | GPU {hw.get('temp_gpu_c', '?')}°C",
                    f"  RAM {hw.get('ram_pct', '?')}% | Power {hw.get('total_power_w', '?')}W",
                    "",
                ]
            if pf:
                lines += [
                    "*Portfolio*",
                    f"  Balance: ${pf.get('balance', 0):,.2f}",
                    f"  Daily PnL: ${pf.get('daily_pnl', 0):,.2f}",
                    "",
                ]
            for name, status in agent_st.items():
                icon = "✅" if status == "up" else "❌"
                lines.append(f"{icon} {name}")

            await slack_send("\n".join(lines))
            log.info("[digest] daily digest sent")
        except Exception as e:
            log.warning(f"[digest] error: {e}")


# ── Startup: launch all background monitors ───────────────────────────────────

@app.on_event("startup")
async def startup():
    log.info("Sovereign Agent starting — launching autonomous monitors")
    asyncio.create_task(monitor_health())
    asyncio.create_task(monitor_hardware())
    asyncio.create_task(monitor_portfolio())
    asyncio.create_task(monitor_tax())
    asyncio.create_task(daily_digest())

    # Send startup notification
    status = await check_all_agents()
    global _agent_status
    _agent_status = status
    up = sum(1 for s in status.values() if s == "up")
    await slack_send(
        f"*Sovereign Agent Online*\n"
        f"{up}/{len(AGENTS)} agents active\n"
        f"Monitoring: hardware every 5min, portfolio every 30min, health every 60s"
    )
    log.info(f"Startup complete — {up}/{len(AGENTS)} agents up")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":       "ok",
        "service":      "sovereign",
        "port":         PORT,
        "agent_status": _agent_status,
        "slack_configured": bool(SLACK_BOT_TOKEN and SLACK_CHANNEL),
    }


@app.get("/status")
async def status():
    """Full system snapshot — all agents + latest hardware + portfolio."""
    agent_st = await check_all_agents()
    return {
        "timestamp":    datetime.now().isoformat(),
        "agents":       agent_st,
        "hardware":     _last_hardware,
        "portfolio":    _last_portfolio,
        "alerts_active": list(_alerts_sent),
    }


@app.get("/agents")
async def agents():
    """List all registered agents with their URLs and current status."""
    return {
        name: {"url": url, "status": _agent_status.get(name, "unknown")}
        for name, url in AGENTS.items()
    }


class AskRequest(BaseModel):
    question: str
    agents:   Optional[list[str]] = None   # force specific agents, or auto-route


class ChainRequest(BaseModel):
    steps: list[dict]   # [{"agent": "tax", "query": "..."}, ...]


@app.post("/ask")
async def ask(req: AskRequest):
    """
    Intelligent multi-agent query. Auto-routes to the right agents,
    calls them in parallel, and synthesizes the results.

    Example:
      {"question": "What is my portfolio worth and what will I owe in taxes?"}
    """
    chosen = req.agents or await _route(req.question)
    log.info(f"[/ask] routing to agents={chosen}: {req.question[:80]}")

    # Call chosen agents in parallel
    results = await asyncio.gather(
        *[_call_agent(name, req.question) for name in chosen],
        return_exceptions=True
    )

    agent_results = {}
    for name, result in zip(chosen, results):
        agent_results[name] = str(result) if isinstance(result, Exception) else result

    # Synthesize with LLM
    context = "\n\n".join(f"[{k}]\n{v}" for k, v in agent_results.items())
    system  = (
        "You are Sovereign — the master AI orchestrator for Skyp_the_Bot. "
        "You have consulted multiple specialized agents and received their responses. "
        "Synthesize their answers into one clear, accurate, helpful response. "
        "Don't repeat agent labels — just give the unified answer."
    )
    prompt  = f"User question: {req.question}\n\nAgent responses:\n{context}"
    answer  = await _ask_ollama(system, prompt)

    return {
        "question":      req.question,
        "agents_used":   chosen,
        "agent_results": agent_results,
        "answer":        answer,
    }


@app.post("/chain")
async def chain(req: ChainRequest):
    """
    Execute an explicit agent chain in sequence.
    Each step can reference the previous step's output via {prev}.

    Example:
      {"steps": [
        {"agent": "maxmillion", "query": "get metrics"},
        {"agent": "tax", "query": "estimate taxes on this data: {prev}"}
      ]}
    """
    results = []
    prev    = ""
    for step in req.steps:
        name  = step.get("agent", "")
        query = step.get("query", "").replace("{prev}", prev[:500])
        log.info(f"[/chain] step agent={name}: {query[:60]}")
        result = await _call_agent(name, query)
        results.append({"agent": name, "query": query, "result": result})
        prev = result

    return {"steps": results, "final": prev}


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Sovereign Agent starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
