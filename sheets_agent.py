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
SHEETS_API   = "https://sheets.googleapis.com/v4/spreadsheets"
SA_JSON      = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(Path.home() / "maxmillion" / "service_account.json"),
)
# Google Apps Script web-app URL (no service account needed — just paste the
# script from the repo's docs into Extensions → Apps Script → Deploy as web app)
SHEETS_WEBAPP_URL = os.environ.get("SHEETS_WEBAPP_URL", "")

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
        "version":     "2.0.0",
        "description": "Read/write crypto portfolio data via Google Sheets for ZeroClaw/MaxMillion",
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
            {
                "path":        "/update_sheet",
                "method":      "POST",
                "description": "Called by MaxMillion after each trade. Appends a row to 'Trade Log' tab.",
                "body_schema": {
                    "trade_id": "string",
                    "symbol":   "string (e.g. BTC/USDT)",
                    "side":     "string (buy|sell)",
                    "qty":      "float",
                    "fill_price": "float",
                    "pnl_tick": "float",
                    "balance":  "float",
                    "ts":       "string (ISO-8601)",
                },
            },
            {
                "path":        "/find_or_update_holding",
                "method":      "POST",
                "description": "Update a coin's Amount/Value row in the holdings tab, or append it.",
                "body_schema": {
                    "symbol":    "string (e.g. BTC)",
                    "amount":    "float",
                    "value_usd": "float (optional)",
                },
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


# ── Write auth helper ─────────────────────────────────────────────────────────
# All write operations need a read+write OAuth token from the service account.
# We cache it for up to 55 minutes to avoid hammering Google's token endpoint.

_write_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


async def _get_write_token() -> str:
    """
    Return a valid Google OAuth2 bearer token with read+write spreadsheet scope.
    Uses the cached token if it is still valid; otherwise fetches a fresh one.

    Raises FileNotFoundError if the service account JSON does not exist.
    Raises ImportError  if neither google-auth nor cryptography is installed.
    Raises HTTPException(503) if the token exchange with Google fails.
    """
    now = time.time()
    if _write_token_cache["token"] and now < _write_token_cache["expires_at"]:
        return _write_token_cache["token"]

    sa    = _load_service_account()
    token = _build_jwt(sa, write=True)

    # google-auth returns the bearer token directly; the crypto fallback returns
    # a raw JWT that must be exchanged at the token endpoint.
    if len(token.split(".")) == 3:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion":  token,
                },
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail=f"Google token exchange failed ({r.status_code}): {r.text}",
            )
        access_token = r.json()["access_token"]
    else:
        access_token = token

    # Cache for 55 minutes (tokens are valid for 60 min; keep 5-min buffer)
    _write_token_cache["token"]      = access_token
    _write_token_cache["expires_at"] = now + 55 * 60
    return access_token


# ── Sheet-write helpers ───────────────────────────────────────────────────────

async def _sheet_append(tab_name: str, rows: list[list]) -> dict:
    """
    Append one or more rows to *tab_name* using the Sheets API append method.
    The range notation "TabName" tells Google to find the first empty row after
    existing data automatically.

    Returns the raw JSON response from the Sheets API.
    Raises HTTPException(503) on auth failure.
    Raises httpx.HTTPStatusError on any non-2xx from Sheets.
    """
    token = await _get_write_token()
    url   = f"{SHEETS_API}/{SHEET_ID}/values/{tab_name}:append"
    body  = {
        "range":          tab_name,
        "majorDimension": "ROWS",
        "values":         rows,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "valueInputOption":        "USER_ENTERED",
                "insertDataOption":        "INSERT_ROWS",
                "includeValuesInResponse": "false",
            },
            json=body,
        )
    r.raise_for_status()
    return r.json()


async def _sheet_get_tab_values(tab_name: str) -> list[list]:
    """
    Read all values from *tab_name* using the Sheets API.
    Returns a list-of-lists (rows x columns), empty list if tab is empty.
    Uses the write token (read+write scope covers read as well).
    """
    token = await _get_write_token()
    url   = f"{SHEETS_API}/{SHEET_ID}/values/{tab_name}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"majorDimension": "ROWS"},
        )
    if r.status_code == 400:
        # Tab does not exist yet — treat as empty
        return []
    r.raise_for_status()
    return r.json().get("values", [])


async def _sheet_update_cell(cell_range: str, value: Any) -> dict:
    """
    Overwrite a single cell (e.g. "Holdings!C3") with *value*.
    Returns the raw JSON response from the Sheets API.
    """
    token = await _get_write_token()
    url   = f"{SHEETS_API}/{SHEET_ID}/values/{cell_range}"
    body  = {
        "range":          cell_range,
        "majorDimension": "ROWS",
        "values":         [[value]],
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.put(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"valueInputOption": "USER_ENTERED"},
            json=body,
        )
    r.raise_for_status()
    return r.json()


async def _ensure_trade_log_header() -> None:
    """
    Make sure the Trade Log tab exists and has the correct header row.
    If the tab is empty (or does not exist), the header is written first so
    every subsequent append lands in the right columns.
    """
    try:
        values = await _sheet_get_tab_values(TRADE_LOG_TAB)
        if not values:
            await _sheet_append(TRADE_LOG_TAB, [TRADE_LOG_COLS])
            log.info("Trade Log header row written.")
    except Exception as exc:
        # Non-fatal — trade rows will still append, just without a header.
        log.warning("Could not ensure Trade Log header: %s", exc)


# ── Write models ──────────────────────────────────────────────────────────────

class TradeRecord(BaseModel):
    """
    The payload MaxMillion POSTs to /update_sheet after every trade.
    All fields map directly to the TRADE_LOG_COLS columns.
    """
    trade_id:   str
    symbol:     str
    side:       str
    qty:        float
    fill_price: float
    pnl_tick:   float
    balance:    float
    ts:         str   # ISO-8601 timestamp


class HoldingUpdate(BaseModel):
    """
    The payload for /find_or_update_holding.
    Updates an existing holdings row or appends a new one.
    """
    symbol:    str
    amount:    float
    value_usd: float | None = None


# ── Write endpoints ───────────────────────────────────────────────────────────

@app.post("/update_sheet")
async def update_sheet(trade: TradeRecord):
    """
    Called by MaxMillion after every mock trade.

    Appends one row to the 'Trade Log' tab with all trade details.
    If the tab is empty, a header row is written first.

    The service account must have *Editor* access to the spreadsheet.
    Set GOOGLE_SERVICE_ACCOUNT_JSON (or place the JSON at ~/maxmillion/service_account.json).

    Returns:
        {
          "status":  "appended",
          "tab":     "Trade Log",
          "row":     [...],        # the values that were written
          "api_response": {...}    # raw Sheets API response
        }
    """
    row_values = [
        trade.trade_id,
        trade.symbol,
        trade.side.upper(),
        trade.qty,
        trade.fill_price,
        trade.pnl_tick,
        trade.balance,
        trade.ts,
    ]

    try:
        # Fast path: Apps Script web app (no service account needed)
        if SHEETS_WEBAPP_URL:
            try:
                result = await _webapp_append_trade(trade)
                log.info("Trade %s logged via Apps Script", trade.trade_id)
                return {"status": "appended", "tab": TRADE_LOG_TAB,
                        "row": row_values, "api_response": result}
            except Exception as exc:
                log.warning("Apps Script append failed, falling back to API: %s", exc)

        await _ensure_trade_log_header()
        api_resp = await _sheet_append(TRADE_LOG_TAB, [row_values])
        log.info(
            "Trade %s logged to sheet tab '%s' (%s %s)",
            trade.trade_id, TRADE_LOG_TAB, trade.side, trade.symbol,
        )
        # Bust the read cache so /portfolio reflects the new state promptly
        _cache["ts"] = 0.0
        return {
            "status":       "appended",
            "tab":          TRADE_LOG_TAB,
            "row":          row_values,
            "api_response": api_resp,
        }
    except FileNotFoundError as exc:
        log.error("Service account missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Service account JSON not found. "
                f"Place it at {SA_JSON} or set GOOGLE_SERVICE_ACCOUNT_JSON. "
                "The service account must have Editor access to the sheet."
            ),
        )
    except ImportError as exc:
        log.error("Auth library missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )
    except httpx.HTTPStatusError as exc:
        log.error("Sheets API error: %s %s", exc.response.status_code, exc.response.text)
        raise HTTPException(
            status_code=502,
            detail=f"Google Sheets API returned {exc.response.status_code}: {exc.response.text}",
        )
    except Exception as exc:
        log.error("Unexpected write error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def _webapp_update_holding(update: HoldingUpdate) -> dict:
    """Write via Google Apps Script web app — no service account needed."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.post(SHEETS_WEBAPP_URL, json={
            "action":    "update_holding",
            "symbol":    update.symbol.upper(),
            "amount":    update.amount,
            "value_usd": update.value_usd,
        })
    r.raise_for_status()
    result = r.json()
    _cache["ts"] = 0.0
    return result


async def _webapp_append_trade(trade: "TradeRecord") -> dict:
    """Append a trade row via Google Apps Script web app."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.post(SHEETS_WEBAPP_URL, json={
            "action":     "append_trade",
            "trade_id":   trade.trade_id,
            "symbol":     trade.symbol,
            "side":       trade.side,
            "qty":        trade.qty,
            "fill_price": trade.fill_price,
            "pnl_tick":   trade.pnl_tick,
            "balance":    trade.balance,
            "ts":         trade.ts,
        })
    r.raise_for_status()
    _cache["ts"] = 0.0
    return r.json()


@app.post("/find_or_update_holding")
async def find_or_update_holding(update: HoldingUpdate):
    """
    Update the holdings section of the sheet for a specific coin.

    Strategy:
      1. Read the first tab (Sheet1) as a list of rows.
      2. Scan for a row whose symbol column matches *update.symbol*.
      3. If found — overwrite the Amount and (optionally) Value cells in place.
      4. If not found — append a new row at the bottom with Symbol, Amount, Value.

    Column detection uses the same fuzzy header matching as /portfolio.

    Returns:
        {
          "action":  "updated" | "appended",
          "symbol":  "BTC",
          "row_index": 3,        # 1-based row number in the sheet (updated case)
          "amount":  0.5,
          "value_usd": 32500.0
        }
    """
    target = update.symbol.strip().upper()

    # Fast path: use Apps Script web app if configured (no service account needed)
    if SHEETS_WEBAPP_URL:
        try:
            return await _webapp_update_holding(update)
        except Exception as exc:
            log.warning("Apps Script write failed, falling back to API: %s", exc)

    try:
        tab    = "Sheet1"   # default first-tab name; adjust via SHEET_GID env
        values = await _sheet_get_tab_values(tab)

        if not values:
            # Empty sheet — write a header then append the holding
            header = ["Symbol", "Amount", "Value USD"]
            await _sheet_append(tab, [header])
            row_data = [target, update.amount, update.value_usd or ""]
            await _sheet_append(tab, [row_data])
            _cache["ts"] = 0.0
            return {
                "action":    "appended",
                "symbol":    target,
                "row_index": 2,
                "amount":    update.amount,
                "value_usd": update.value_usd,
            }

        headers = [str(h).strip().lower() for h in values[0]]

        # Locate the symbol, amount, and value columns (1-based for Sheets API)
        sym_candidates = ["symbol", "coin", "ticker", "asset", "currency", "name"]
        amt_candidates = ["amount", "qty", "quantity", "balance", "holdings"]
        val_candidates = ["value", "current_value", "usd_value", "total_value", "worth", "value usd"]

        def _col_index(candidates: list[str]) -> int | None:
            for c in candidates:
                if c.lower() in headers:
                    return headers.index(c.lower()) + 1   # 1-based
            return None

        sym_col_idx = _col_index(sym_candidates)
        amt_col_idx = _col_index(amt_candidates)
        val_col_idx = _col_index(val_candidates)

        if sym_col_idx is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Cannot identify a symbol/coin column in the sheet. "
                    f"Detected headers: {list(values[0])}"
                ),
            )

        # Search for an existing row for this symbol (rows are 1-based; row 1 = header)
        def _col_letter(idx: int) -> str:
            """Convert 1-based column index to A-Z / AA-AZ letter(s)."""
            result = ""
            while idx > 0:
                idx, rem = divmod(idx - 1, 26)
                result   = chr(65 + rem) + result
            return result

        found_row = None
        for row_idx, row in enumerate(values[1:], start=2):   # start=2: skip header
            if len(row) >= sym_col_idx:
                cell_val = str(row[sym_col_idx - 1]).strip().upper()
                if cell_val == target:
                    found_row = row_idx
                    break

        if found_row is not None:
            # Update amount cell in place
            if amt_col_idx:
                amt_cell = f"{tab}!{_col_letter(amt_col_idx)}{found_row}"
                await _sheet_update_cell(amt_cell, update.amount)
            # Update value cell in place (if column exists and value provided)
            if val_col_idx and update.value_usd is not None:
                val_cell = f"{tab}!{_col_letter(val_col_idx)}{found_row}"
                await _sheet_update_cell(val_cell, update.value_usd)

            log.info(
                "Updated holding %s at row %d (amt=%.6f val=%s)",
                target, found_row, update.amount, update.value_usd,
            )
            _cache["ts"] = 0.0
            return {
                "action":    "updated",
                "symbol":    target,
                "row_index": found_row,
                "amount":    update.amount,
                "value_usd": update.value_usd,
            }
        else:
            # Symbol not in sheet — append a new row
            new_row: list[Any] = [""] * len(headers)
            new_row[sym_col_idx - 1] = target
            if amt_col_idx:
                new_row[amt_col_idx - 1] = update.amount
            if val_col_idx and update.value_usd is not None:
                new_row[val_col_idx - 1] = update.value_usd
            await _sheet_append(tab, [new_row])

            log.info("Appended new holding row for %s (amt=%.6f)", target, update.amount)
            _cache["ts"] = 0.0
            return {
                "action":    "appended",
                "symbol":    target,
                "row_index": len(values) + 1,
                "amount":    update.amount,
                "value_usd": update.value_usd,
            }

    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Service account JSON not found. "
                f"Place it at {SA_JSON} or set GOOGLE_SERVICE_ACCOUNT_JSON."
            ),
        )
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Google Sheets API returned {exc.response.status_code}: {exc.response.text}",
        )
    except Exception as exc:
        log.error("find_or_update_holding error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── CoinGecko price sync ──────────────────────────────────────────────────────

# Maps ticker symbol → CoinGecko ID
COINGECKO_IDS: dict[str, str] = {
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "SOL":   "solana",
    "BNB":   "binancecoin",
    "DOGE":  "dogecoin",
    "ADA":   "cardano",
    "XRP":   "ripple",
    "AVAX":  "avalanche-2",
    "MATIC": "matic-network",
    "DOT":   "polkadot",
    "LINK":  "chainlink",
    "LTC":   "litecoin",
    "UNI":   "uniswap",
    "ATOM":  "cosmos",
    "TRX":   "tron",
    "NEAR":  "near",
    "APT":   "aptos",
    "OP":    "optimism",
    "ARB":   "arbitrum",
    "SUI":   "sui",
    "XLM":   "stellar",
    "HBAR":  "hedera-hashgraph",
    "ALGO":  "algorand",
    "VET":   "vechain",
    "SEI":   "sei-network",
    "CSPR":  "casper-network",
    "XDC":   "xdce-crowd-sale",
    "SWFTC": "swftcoin",
    "VELO":  "velo",
    "XPR":   "proton",
    "WLFI":  "world-liberty-financial",
    "ZBCN":  "zebec-network",
    "SNIPS": "snips",
}

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


async def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch current USD prices for a list of ticker symbols via CoinGecko."""
    ids_needed = {}
    for sym in symbols:
        clean = sym.upper().replace("/USDT", "").replace("/USD", "").strip()
        cg_id = COINGECKO_IDS.get(clean)
        if cg_id:
            ids_needed[clean] = cg_id

    if not ids_needed:
        return {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(COINGECKO_URL, params={
                "ids":           ",".join(ids_needed.values()),
                "vs_currencies": "usd",
            })
            r.raise_for_status()
            data = r.json()

        prices: dict[str, float] = {}
        for sym, cg_id in ids_needed.items():
            if cg_id in data and "usd" in data[cg_id]:
                prices[sym] = data[cg_id]["usd"]
        return prices
    except Exception as e:
        log.warning(f"CoinGecko fetch failed: {e}")
        return {}


@app.post("/sync_prices")
async def sync_prices():
    """
    Fetch live prices from CoinGecko and update each holding's Value column
    in the Google Sheet. Requires service account with Editor access.

    Returns a summary of what was updated.
    """
    rows = await get_rows(force=True)
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in sheet.")

    sym_col = _symbol_col(rows)
    amt_col = _amount_col(rows)
    if not sym_col:
        raise HTTPException(status_code=422,
                            detail="Cannot find a symbol column in the sheet.")

    # Collect all unique symbols
    symbols = list({str(r.get(sym_col, "")).upper().strip()
                    for r in rows if r.get(sym_col)})
    log.info(f"[sync_prices] fetching prices for: {symbols}")

    prices = await fetch_prices(symbols)
    if not prices:
        raise HTTPException(status_code=503,
                            detail="CoinGecko returned no prices. Try again in a moment.")

    updated = []
    skipped = []

    for row in rows:
        sym = str(row.get(sym_col, "")).upper().strip()
        clean = sym.replace("/USDT", "").replace("/USD", "")
        price = prices.get(clean)
        if price is None:
            skipped.append(sym)
            continue

        amount = _to_float(row.get(amt_col)) if amt_col else None
        value  = round(price * amount, 2) if amount else None

        try:
            await find_or_update_holding(HoldingUpdate(
                symbol=clean, amount=amount or 0.0, value_usd=value
            ))
            updated.append({
                "symbol":    clean,
                "price_usd": price,
                "amount":    amount,
                "value_usd": value,
            })
        except Exception as e:
            log.warning(f"[sync_prices] failed to update {sym}: {e}")
            skipped.append(sym)

    _cache["ts"] = 0.0   # bust cache
    log.info(f"[sync_prices] updated={len(updated)} skipped={len(skipped)}")
    return {
        "updated": updated,
        "skipped": skipped,
        "prices_fetched": prices,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/prices")
async def get_prices():
    """Return current market prices for all symbols found in the sheet."""
    rows = await get_rows()
    sym_col = _symbol_col(rows)
    if not sym_col:
        raise HTTPException(status_code=422, detail="No symbol column found.")
    symbols = list({str(r.get(sym_col, "")).upper().strip()
                    for r in rows if r.get(sym_col)})
    prices = await fetch_prices(symbols)
    return {"prices": prices, "symbols_checked": symbols}


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
