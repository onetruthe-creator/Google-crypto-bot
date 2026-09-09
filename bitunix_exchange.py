"""
Bitunix REST API adapter (spot).
Base URL: https://openapi.bitunix.com
Signature: two-step SHA256 — SHA256(nonce+ts+key+query+body) then SHA256(digest+secret)
"""

import os
import base64
import hashlib
import logging
import requests
import pandas as pd
from config import (
    EXCHANGE_API_KEY, EXCHANGE_SECRET,
    TRADING_PAIR, CANDLE_TIMEFRAME, TRADE_AMOUNT_USDT,
)

BASE_URL = "https://openapi.bitunix.com"
log = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "6h":  "6h",
    "12h": "12h",
    "1d":  "1d",
}


def _symbol(pair: str) -> str:
    """'BTC/USDT' → 'BTCUSDT'"""
    return pair.replace("/", "")


def _nonce() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _sign(nonce: str, timestamp: str, query: str = "", body: str = "") -> str:
    """Two-step SHA256 signature required by Bitunix."""
    step1 = hashlib.sha256(
        (nonce + timestamp + EXCHANGE_API_KEY + query + body).encode()
    ).hexdigest()
    return hashlib.sha256((step1 + EXCHANGE_SECRET).encode()).hexdigest()


def _auth_headers(query: str = "", body: str = "") -> dict:
    import time
    ts = str(int(time.time() * 1000))
    nonce = _nonce()
    return {
        "api-key":    EXCHANGE_API_KEY,
        "timestamp":  ts,
        "nonce":      nonce,
        "sign":       _sign(nonce, ts, query, body),
        "Content-Type": "application/json",
    }


def _ok(code) -> bool:
    """Accept Bitunix success codes returned as int or string."""
    return int(code) in (0, 200)


def _get_public(path: str, params: dict) -> dict:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    url = f"{BASE_URL}{path}?{query}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not _ok(data.get("code", 0)):
        raise RuntimeError(f"Bitunix error {data.get('code')}: {data.get('msg')}")
    return data


def _get_private(path: str, params: dict) -> dict:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    headers = _auth_headers(query=query)
    url = f"{BASE_URL}{path}?{query}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not _ok(data.get("code", 0)):
        raise RuntimeError(f"Bitunix error {data.get('code')}: {data.get('msg')}")
    return data


def _post_private(path: str, body: dict) -> dict:
    import json
    body_str = json.dumps(body, separators=(",", ":"))
    headers = _auth_headers(body=body_str)
    resp = requests.post(BASE_URL + path, data=body_str, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not _ok(data.get("code", 0)):
        raise RuntimeError(f"Bitunix error {data.get('code')}: {data.get('msg')}")
    return data


# ── Public interface ─────────────────────────────────────────────────────────

class BitunixExchange:
    pass


def get_exchange(dry_run: bool = True) -> BitunixExchange:
    return BitunixExchange()


def fetch_ohlcv(exchange: BitunixExchange) -> pd.DataFrame:
    interval = TIMEFRAME_MAP.get(CANDLE_TIMEFRAME, "15m")
    data = _get_public("/api/spot/v1/market/kline", {
        "symbol":   _symbol(TRADING_PAIR),
        "interval": interval,
        "limit":    100,
    })
    candles = data["data"]
    df = pd.DataFrame(candles)
    # Normalise column names — Bitunix may return open_time / o / h / l / c / v
    rename = {
        "open_time": "timestamp", "t": "timestamp",
        "o": "open",  "open":  "open",
        "h": "high",  "high":  "high",
        "l": "low",   "low":   "low",
        "c": "close", "close": "close",
        "v": "volume","vol":   "volume", "volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="ms")
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_ticker(exchange: BitunixExchange) -> dict:
    data = _get_public("/api/spot/v1/market/last_price", {"symbol": _symbol(TRADING_PAIR)})
    t = data["data"]
    price = float(t.get("last_price", t.get("price", t.get("lastPrice", 0))))
    return {
        "last":        price,
        "high":        float(t.get("high", 0)),
        "low":         float(t.get("low", 0)),
        "percentage":  float(t.get("change_rate", t.get("priceChangePercent", 0))),
        "quoteVolume": float(t.get("quote_volume", t.get("volume", 0))),
    }


def fetch_balance(exchange: BitunixExchange) -> dict:
    base, quote = TRADING_PAIR.split("/")
    if not (EXCHANGE_API_KEY and EXCHANGE_SECRET):
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}
    try:
        data = _get_private("/api/spot/v1/user/account", {})
        assets = {}
        raw = data.get("data", [])
        items = raw if isinstance(raw, list) else raw.get("assets", [])
        for item in items:
            if isinstance(item, dict):
                coin = item.get("coin", item.get("currency", ""))
                assets[coin] = float(item.get("available", item.get("free", 0)))
        log.info("Bitunix wallet coins: %s", list(assets.keys()))
        log.info("Bitunix raw items: %s", items)
        return {
            "base":           assets.get(base, 0.0),
            "quote":          assets.get(quote, 0.0),
            "base_currency":  base,
            "quote_currency": quote,
        }
    except Exception as exc:
        log.warning("Balance fetch failed: %s", exc)
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}


def place_market_order(exchange: BitunixExchange, side: str, amount_usdt: float, ticker: dict) -> dict:
    price = ticker["last"]
    qty = round(amount_usdt / price, 6)
    return _post_private("/api/spot/v1/order/place_order", {
        "symbol": _symbol(TRADING_PAIR),
        "side":   side.upper(),
        "type":   "MARKET",
        "qty":    str(qty),
    })
