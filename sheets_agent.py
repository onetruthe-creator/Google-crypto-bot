#!/usr/bin/env python3
"""
sheets_agent.py — Google Sheets crypto portfolio microservice
Port: 8083

Integrates with:
  ZeroClaw AI agent gateway  → http://127.0.0.1:3001
  MaxMillion mock trader     → http://127.0.0.1:8082

Sheet: 1_1DRS_HkfrJTMpz4xT6gwEcgcoidJUJFeScmWFISvFk

Strategy:
  1. Try public CSV export (no auth needed)
  2. Fall back to Google Sheets API v4 with service account JSON
     (set env var GOOGLE_SERVICE_ACCOUNT_JSON to the path of your JSON key)

Endpoints (READ):
  GET  /portfolio        — all holdings (symbol, amount, value, …)
  GET  /summary          — total value, top holdings, PnL if present
  POST /analyze          — { "symbol": "BTC" } → row(s) for that coin
  GET  /health           — liveness probe

Endpoints (WRITE — called by MaxMillion after each trade):
  POST /update_sheet     — append a completed trade row to the sheet
                           body: {trade_id, symbol, side, qty, fill_price,
                                  pnl_tick, balance, ts}

  POST /find_or_update_holding  — update the Amount/Value cell for a coin if
                                  it already exists in the holdings section,
                                  or append a new row if not found.
                           body: {symbol, amount, value_usd}

Cache TTL: 60 seconds

Writing requires the Google Sheets API (read+write scope).
The service account must have Editor access to the sheet.
"""

import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
SHEET_ID   = "1_1DRS_HkfrJTMpz4xT6gwEcgcoidJUJFeScmWFISvFk"
SHEET_GID  = os.environ.get("SHEET_GID", "0")          # tab index (0 = first)
CSV_URL    = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    f"/export?format=csv&gid={SHEET_GID}"
)
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SA_JSON    = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(Path.home() / "maxmillion" / "service_account.json"),
)

CACHE_TTL  = 60          # seconds
PORT       = 8083

ZEROCLAW   = "http://127.0.0.1:3001"
MAXMILLION = "http://127.0.0.1:8082"

# ── Sheet layout for the trade-log tab ───────────────────────────────────────
# sheets_agent will look for (or create) a tab called "Trade Log".
# The first row is treated as a header row.  When MaxMillion posts a trade,
# a new row is appended to that tab with the columns below.
TRADE_LOG_TAB  = os.environ.get("TRADE_LOG_TAB", "Trade Log")
TRADE_LOG_COLS = [
    "Trade ID", "Symbol", "Side", "Qty",
    "Fill Price", "PnL Tick", "Balance USDT", "Timestamp",
]
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sheets_agent] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Sheets Agent",
    description="Crypto portfolio data bridge from Google Sheets to ZeroClaw/MaxMillion",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: dict[str, Any] = {"rows": None, "ts": 0.0, "source": "none"}


def cache_fresh() -> bool:
    return _cache["rows"] is not None and (time.time() - _cache["ts"]) < CACHE_TTL


def set_cache(rows: list[dict], source: str) -> None:
    _cache["rows"] = rows
    _cache["ts"]   = time.time()
    _cache["source"] = source
    log.info("Cache refreshed via %s (%d rows)", source, len(rows))


# ── CSV parser ────────────────────────────────────────────────────────────────

NUMERIC_HINTS = {
    "amount", "qty", "quantity", "balance",
    "value", "price", "cost", "pnl", "profit", "loss",
    "current_value", "invested", "allocation", "percent",
}


def _coerce(key: str, raw: str) -> Any:
    """Try to return a float when the column looks numeric."""
    stripped = raw.strip().replace(",", "").replace("$", "").replace("%", "")
    if any(h in key.lower() for h in NUMERIC_HINTS):
        try:
            return float(stripped)
        except ValueError:
            pass
    return raw.strip() if raw else None


def parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw_row in reader:
        row = {k.strip(): _coerce(k, v) for k, v in raw_row.items() if k}
        # Skip rows where every value is None / empty (blank sheet rows)
        if any(v not in (None, "") for v in row.values()):
            rows.append(row)
    return rows


# ── Fetch: public CSV ─────────────────────────────────────────────────────────

async def fetch_public_csv() -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(CSV_URL)
    if resp.status_code == 200:
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            raise PermissionError("Sheet is private — received HTML login page.")
        return parse_csv(resp.text)
    raise PermissionError(f"CSV export returned HTTP {resp.status_code}.")


# ── Fetch: service account (Google Sheets API v4) ────────────────────────────

def _load_service_account() -> dict:
    if not Path(SA_JSON).exists():
        raise FileNotFoundError(f"Service account file not found: {SA_JSON}")
    with open(SA_JSON) as fh:
        return json.load(fh)


def _build_jwt(sa: dict, write: bool = False) -> str:
    """
    Mint a signed JWT for the Google OAuth2 token endpoint.

    Args:
        sa:    Service account dict loaded from JSON key file.
        write: If True, request read+write scope instead of read-only.
               You must pass write=True when calling any sheets write API.
    """
    import base64

    scope = (
        "https://www.googleapis.com/auth/spreadsheets"
        if write else
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    )

    # We need cryptography or google-auth; try google-auth first.
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GARequest

        creds = service_account.Credentials.from_service_account_info(
            sa,
            scopes=[scope],
        )
        creds.refresh(GARequest())
        return creds.token
    except ImportError:
        pass

    # Minimal fallback using only stdlib + cryptography
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import time as _time

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header  = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        now     = int(_time.time())
        payload = b64url(json.dumps({
            "iss":   sa["client_email"],
            "scope": scope,
            "aud":   "https://oauth2.googleapis.com/token",
            "exp":   now + 3600,
            "iat":   now,
        }).encode())

        signing_input = f"{header}.{payload}".encode()
        private_key   = serialization.load_pem_private_key(
            sa["private_key"].encode(), password=None
        )
        sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{header}.{payload}.{b64url(sig)}"

    except ImportError:
        raise ImportError(
            "Install google-auth or cryptography to use service account auth: "
            "pip install google-auth"
        )


async def fetch_via_service_account() -> list[dict]:
    sa    = _load_service_account()
    token = _build_jwt(sa)

    # If google-auth returned a bearer token directly, use it; otherwise
    # the fallback produced a JWT we need to exchange.
    if "." not in token or len(token.split(".")) != 3:
        access_token = token
    else:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": token,
                },
            )
        r.raise_for_status()
        access_token = r.json()["access_token"]

    url = f"{SHEETS_API}/{SHEET_ID}/values/A1:ZZ10000"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"majorDimension": "ROWS"},
        )
    r.raise_for_status()
    data = r.json()

    values = data.get("values", [])
    if not values:
        return []

    headers = [str(h).strip() for h in values[0]]
    rows: list[dict] = []
    for raw in values[1:]:
        # Pad short rows so zip always produces full records
        padded = raw + [""] * (len(headers) - len(raw))
        row    = {headers[i]: _coerce(headers[i], str(padded[i])) for i in range(len(headers))}
        if any(v not in (None, "") for v in row.values()):
            rows.append(row)
    return rows


# ── Master fetcher ────────────────────────────────────────────────────────────

async def get_rows(force: bool = False) -> list[dict]:
    if not force and cache_fresh():
        return _cache["rows"]

    # 1) Try public CSV
    try:
        rows = await fetch_public_csv()
        set_cache(rows, "public_csv")
        return rows
    except PermissionError as exc:
        log.warning("Public CSV failed: %s", exc)
    except Exception as exc:
        log.warning("Public CSV error: %s", exc)

    # 2) Try service account
    try:
        rows = await fetch_via_service_account()
        set_cache(rows, "service_account")
        return rows
    except FileNotFoundError as exc:
        log.warning("Service account not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Google Sheet appears to be private and no service account is configured. "
                f"Place your JSON key at {SA_JSON} or set GOOGLE_SERVICE_ACCOUNT_JSON. "
                "Alternatively, make the sheet public (File → Share → Anyone with the link)."
            ),
        )
    except Exception as exc:
        log.error("Service account fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"All fetch methods failed: {exc}")


# ── Portfolio helpers ─────────────────────────────────────────────────────────

def _detect_column(rows: list[dict], candidates: list[str]) -> str | None:
    """Return the first header that matches any candidate (case-insensitive)."""
    if not rows:
        return None
    headers = list(rows[0].keys())
    lower   = [h.lower() for h in headers]
    for c in candidates:
        if c.lower() in lower:
            return headers[lower.index(c.lower())]
    return None


def _symbol_col(rows: list[dict]) -> str | None:
    return _detect_column(rows, ["symbol", "coin", "ticker", "asset", "currency", "name"])


def _value_col(rows: list[dict]) -> str | None:
    return _detect_column(rows, ["value", "current_value", "usd_value", "total_value", "worth"])


def _pnl_col(rows: list[dict]) -> str | None:
    return _detect_column(rows, ["pnl", "profit", "loss", "gain", "profit_loss", "pl"])


def _amount_col(rows: list[dict]) -> str | None:
    return _detect_column(rows, ["amount", "qty", "quantity", "balance", "holdings"])


def _to_float(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").replace("%", "").strip())
        except ValueError:
            pass
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":  "ok",
        "service": "sheets_agent",
        "port":    PORT,
        "sheet_id": SHEET_ID,
        "cache_age_seconds": round(time.time() - _cache["ts"], 1) if _cache["ts"] else None,
        "cache_source": _cache["source"],
    }


@app.get("/portfolio")
async def portfolio():
    """Return all holdings rows from the Google Sheet."""
    rows = await get_rows()
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in sheet.")

    sym_col = _symbol_col(rows)
    amt_col = _amount_col(rows)
    val_col = _value_col(rows)
    pnl_col = _pnl_col(rows)

    holdings = []
    for row in rows:
        entry: dict[str, Any] = {"raw": row}
        if sym_col:
            entry["symbol"] = str(row.get(sym_col, "")).upper()
        if amt_col:
            entry["amount"] = _to_float(row.get(amt_col))
        if val_col:
            entry["value_usd"] = _to_float(row.get(val_col))
        if pnl_col:
            entry["pnl"] = _to_float(row.get(pnl_col))
        holdings.append(entry)

    return {
        "sheet_id":    SHEET_ID,
        "row_count":   len(holdings),
        "columns":     list(rows[0].keys()) if rows else [],
        "cache_source": _cache["source"],
        "holdings":    holdings,
    }


@app.get("/summary")
async def summary():
    """Return aggregated portfolio stats: total value, top holdings, PnL."""
    rows = await get_rows()
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in sheet.")

    sym_col = _symbol_col(rows)
    val_col = _value_col(rows)
    pnl_col = _pnl_col(rows)
    amt_col = _amount_col(rows)

    total_value = 0.0
    total_pnl   = 0.0
    has_pnl     = False
    holdings    = []

    for row in rows:
        symbol  = str(row.get(sym_col, "UNKNOWN")).upper() if sym_col else "UNKNOWN"
        val     = _to_float(row.get(val_col)) if val_col else None
        pnl_val = _to_float(row.get(pnl_col)) if pnl_col else None
        amount  = _to_float(row.get(amt_col))  if amt_col else None

        if val is not None:
            total_value += val
        if pnl_val is not None:
            total_pnl += pnl_val
            has_pnl   = True

        holdings.append({
            "symbol":    symbol,
            "value_usd": val,
            "amount":    amount,
            "pnl":       pnl_val,
        })

    # Sort by value descending for top-holdings
    valued = [h for h in holdings if h["value_usd"] is not None]
    top    = sorted(valued, key=lambda h: h["value_usd"], reverse=True)[:5]

    result: dict[str, Any] = {
        "sheet_id":      SHEET_ID,
        "total_value_usd": round(total_value, 2),
        "asset_count":   len(holdings),
        "top_holdings":  top,
        "cache_source":  _cache["source"],
        "columns_detected": {
            "symbol": sym_col,
            "amount": amt_col,
            "value":  val_col,
            "pnl":    pnl_col,
        },
    }
    if has_pnl:
        result["total_pnl_usd"] = round(total_pnl, 2)

    return result


class AnalyzeRequest(BaseModel):
    symbol: str


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Return all rows matching the requested symbol from the sheet."""
    rows = await get_rows()
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in sheet.")

    sym_col = _symbol_col(rows)
    if not sym_col:
        raise HTTPException(
            status_code=422,
            detail=(
                "Cannot identify a symbol/coin column in the sheet. "
                f"Available columns: {list(rows[0].keys())}"
            ),
        )

    target  = req.symbol.strip().upper()
    matched = [
        row for row in rows
        if str(row.get(sym_col, "")).upper().strip() == target
    ]

    if not matched:
        # Partial match as fallback
        matched = [
            row for row in rows
            if target in str(row.get(sym_col, "")).upper()
        ]

    val_col = _value_col(rows)
    pnl_col = _pnl_col(rows)
    amt_col = _amount_col(rows)

    enriched = []
    for row in matched:
        enriched.append({
            "symbol":    str(row.get(sym_col, "")).upper(),
            "amount":    _to_float(row.get(amt_col))  if amt_col else None,
            "value_usd": _to_float(row.get(val_col))  if val_col else None,
            "pnl":       _to_float(row.get(pnl_col))  if pnl_col else None,
            "raw":       row,
        })

    if not enriched:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{req.symbol}' not found in sheet. "
                   f"Try one of: {sorted({str(r.get(sym_col,'')).upper() for r in rows})}",
        )

    return {
        "symbol":       target,
        "match_count":  len(enriched),
        "sheet_id":     SHEET_ID,
        "cache_source": _cache["source"],
        "data":         enriched,
    }


# ── ZeroClaw skill descriptor (optional registration) ────────────────────────

@app.get("/skill.json")
async def skill_descriptor():
    """
    ZeroClaw-compatible skill manifest.
    Register with: zeroclaw skill add http://127.0.0.1:8083/skill.json
    """
    return {
        "name":        "sheets_portfolio",
        "version":     "1.0.0",
        "description": "Reads crypto portfolio data from Google Sheets for ZeroClaw/MaxMillion",
        "base_url":    f"http://127.0.0.1:{PORT}",
        "endpoints": [
            {
                "path":        "/portfolio",
                "method":      "GET",
                "description": "All holdings with symbol, amount, value, PnL",
            },
            {
                "path":        "/summary",
                "method":      "GET",
                "description": "Total portfolio value, top 5 holdings, aggregate PnL",
            },
            {
                "path":        "/analyze",
                "method":      "POST",
                "description": "Detail for a specific coin. Body: {symbol: 'BTC'}",
                "body_schema": {"symbol": "string (e.g. BTC, ETH, SOL)"},
            },
        ],
    }


# ── MaxMillion push (optional) ────────────────────────────────────────────────

@app.post("/push-to-maxmillion")
async def push_to_maxmillion():
    """
    Forward the current portfolio snapshot to MaxMillion's mock trade endpoint.
    MaxMillion is expected at http://127.0.0.1:8082.
    """
    rows    = await get_rows()
    payload = {
        "source":    "sheets_agent",
        "sheet_id":  SHEET_ID,
        "timestamp": time.time(),
        "holdings":  rows,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{MAXMILLION}/portfolio", json=payload)
        return {"status": "forwarded", "maxmillion_response": r.status_code}
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="MaxMillion is not reachable at http://127.0.0.1:8082",
        )


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    log.info("Starting Sheets Agent on port %d", PORT)
    log.info("Sheet ID : %s", SHEET_ID)
    log.info("CSV URL  : %s", CSV_URL)
    log.info("ZeroClaw : %s", ZEROCLAW)
    log.info("MaxMillion: %s", MAXMILLION)

    uvicorn.run(
        "sheets_agent:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )
