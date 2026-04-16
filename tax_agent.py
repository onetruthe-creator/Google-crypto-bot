#!/usr/bin/env python3
"""
Skyp Tax Agent — Crypto + Income Tax Calculator (port 8087)

Endpoints:
  GET  /health       — service check
  GET  /summary      — auto-fetch MaxMillion + Sheets data, return tax estimate
  GET  /report       — HTML tax report page
  POST /calculate    — manual calculation: {annual_income, capital_gains, filing_status}
  POST /ask          — natural language tax question answered by ZeroClaw/Ollama

systemd service:
  sudo tee /etc/systemd/system/tax-agent.service > /dev/null << 'EOF'
  [Unit]
  Description=Skyp Tax Agent
  After=network.target
  [Service]
  Type=simple
  User=damon
  WorkingDirectory=/home/damon/maxmillion
  ExecStart=/home/damon/maxmillion/venv/bin/python tax_agent.py
  Restart=always
  RestartSec=5
  [Install]
  WantedBy=multi-user.target
  EOF
  sudo systemctl daemon-reload && sudo systemctl enable tax-agent && sudo systemctl start tax-agent
"""

import logging
import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
PORT           = 8087
MAXMILLION_URL = "http://localhost:8082"
SHEETS_URL     = "http://localhost:8083"
OLLAMA_URL     = "http://localhost:11434/v1/chat/completions"
MODEL          = "zeroclaw:latest"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Skyp Tax Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 2024 Federal Tax Brackets ─────────────────────────────────────────────────

BRACKETS = {
    "single": [
        (11600,  0.10),
        (47150,  0.12),
        (100525, 0.22),
        (191950, 0.24),
        (243725, 0.32),
        (609350, 0.35),
        (float("inf"), 0.37),
    ],
    "married": [
        (23200,  0.10),
        (94300,  0.12),
        (201050, 0.22),
        (383900, 0.24),
        (487450, 0.32),
        (731200, 0.35),
        (float("inf"), 0.37),
    ],
}

STANDARD_DEDUCTIONS = {"single": 14600, "married": 29200}

LTCG_RATES = {
    "single":  [(47025, 0.0), (518900, 0.15), (float("inf"), 0.20)],
    "married": [(94050, 0.0), (583750, 0.15), (float("inf"), 0.20)],
}


def calc_income_tax(taxable_income: float, filing_status: str) -> float:
    brackets = BRACKETS.get(filing_status, BRACKETS["single"])
    tax = 0.0
    prev = 0.0
    for limit, rate in brackets:
        if taxable_income <= prev:
            break
        chunk = min(taxable_income, limit) - prev
        tax += chunk * rate
        prev = limit
    return round(tax, 2)


def calc_ltcg_tax(gains: float, income: float, filing_status: str) -> float:
    rates = LTCG_RATES.get(filing_status, LTCG_RATES["single"])
    for limit, rate in rates:
        if income <= limit:
            return round(gains * rate, 2)
    return round(gains * 0.20, 2)


def build_tax_breakdown(annual_income: float, capital_gains: float,
                         capital_gains_lt: float, filing_status: str) -> dict:
    deduction  = STANDARD_DEDUCTIONS.get(filing_status, 14600)
    st_gains   = max(0.0, capital_gains)      # short-term treated as ordinary income
    lt_gains   = max(0.0, capital_gains_lt)

    taxable    = max(0.0, annual_income + st_gains - deduction)
    income_tax = calc_income_tax(taxable, filing_status)
    ltcg_tax   = calc_ltcg_tax(lt_gains, annual_income, filing_status)
    total_tax  = round(income_tax + ltcg_tax, 2)
    quarterly  = round(total_tax / 4, 2)

    return {
        "annual_income":       round(annual_income, 2),
        "short_term_gains":    round(st_gains, 2),
        "long_term_gains":     round(lt_gains, 2),
        "standard_deduction":  deduction,
        "taxable_income":      round(taxable, 2),
        "income_tax":          income_tax,
        "ltcg_tax":            ltcg_tax,
        "total_federal_tax":   total_tax,
        "quarterly_payment":   quarterly,
        "effective_rate":      round(total_tax / max(1, annual_income + st_gains + lt_gains) * 100, 2),
        "filing_status":       filing_status,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "tax-agent", "port": PORT}


class CalcRequest(BaseModel):
    annual_income:    float = 0.0
    capital_gains:    float = 0.0   # short-term
    capital_gains_lt: float = 0.0   # long-term
    filing_status:    str   = "single"


@app.post("/calculate")
def calculate(req: CalcRequest):
    return build_tax_breakdown(
        req.annual_income, req.capital_gains,
        req.capital_gains_lt, req.filing_status
    )


@app.get("/summary")
async def summary():
    mm_data     = {}
    sheets_data = {}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            mm   = await client.get(f"{MAXMILLION_URL}/metrics")
            sh   = await client.get(f"{SHEETS_URL}/summary")
            mm_data     = mm.json()  if mm.status_code == 200  else {}
            sheets_data = sh.json()  if sh.status_code == 200  else {}
    except Exception as e:
        log.warning(f"Data fetch error: {e}")

    pnl          = mm_data.get("daily_pnl", 0.0)
    balance      = mm_data.get("balance",   10000.0)
    total_value  = sheets_data.get("total_value_usd", 0.0)
    capital_gain = max(0.0, pnl)

    breakdown = build_tax_breakdown(
        annual_income=balance,
        capital_gains=capital_gain,
        capital_gains_lt=0.0,
        filing_status="single",
    )
    breakdown["maxmillion_balance"] = balance
    breakdown["portfolio_value"]    = total_value
    breakdown["realized_pnl"]       = pnl
    breakdown["note"] = "Estimate only. Consult a licensed CPA or tax attorney."
    return breakdown


@app.get("/report", response_class=HTMLResponse)
async def report():
    data = await summary()
    if hasattr(data, "body"):
        import json
        data = json.loads(data.body)

    rows = "".join(
        f"<tr><td>{k.replace('_',' ').title()}</td><td>${v:,.2f}"
        f"{'%' if k=='effective_rate' else ''}</td></tr>"
        if isinstance(v, (int, float)) else f"<tr><td>{k.replace('_',' ').title()}</td><td>{v}</td></tr>"
        for k, v in data.items()
    )

    html = f"""<!DOCTYPE html>
<html><head><title>Skyp Tax Report</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:700px;margin:40px auto;background:#0d1117;color:#c9d1d9}}
  h1{{color:#58a6ff}} h2{{color:#79c0ff}}
  table{{width:100%;border-collapse:collapse;margin-top:20px}}
  th{{background:#161b22;color:#58a6ff;padding:10px;text-align:left}}
  td{{padding:8px 10px;border-bottom:1px solid #21262d}}
  tr:hover td{{background:#161b22}}
  .warn{{color:#f0883e;font-size:12px;margin-top:20px}}
  .q{{background:#1f6feb;color:#fff;padding:10px 16px;border-radius:6px;display:inline-block;margin:4px}}
</style></head>
<body>
<h1>📊 Skyp Tax Report</h1>
<h2>2024 Federal Tax Estimate</h2>
<table><tr><th>Item</th><th>Amount</th></tr>{rows}</table>
<h2>📅 Quarterly Payments</h2>
<div>
  <span class="q">Q1 (Apr 15): ${data.get('quarterly_payment',0):,.2f}</span>
  <span class="q">Q2 (Jun 15): ${data.get('quarterly_payment',0):,.2f}</span>
  <span class="q">Q3 (Sep 15): ${data.get('quarterly_payment',0):,.2f}</span>
  <span class="q">Q4 (Jan 15): ${data.get('quarterly_payment',0):,.2f}</span>
</div>
<p class="warn">⚠️ This is an estimate for educational purposes only. Not legal or tax advice. Consult a licensed CPA or tax attorney.</p>
</body></html>"""
    return HTMLResponse(content=html)


class AskRequest(BaseModel):
    question: str


@app.post("/ask")
async def ask(req: AskRequest):
    system = (
        "You are Skyp_the_Bot, an expert tax attorney and CPA. "
        "You specialize in US federal and state tax law, crypto capital gains, "
        "IRS procedures, and tax planning. Always add: "
        "'This is informational only — not tax or legal advice.'"
    )
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":    MODEL,
                "messages": [
                    {"role": "system",  "content": system},
                    {"role": "user",    "content": req.question},
                ],
            })
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"Tax agent error: {e}"
    return {"response": answer}


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Skyp Tax Agent starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
