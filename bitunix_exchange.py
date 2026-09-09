"""
Direct Bitunix REST API adapter.
Implements the same interface as exchange.py so bot.py needs no changes.
"""

import time
import hmac
import hashlib
import requests
import pandas as pd
from config import (
    EXCHANGE_API_KEY, EXCHANGE_SECRET,
    TRADING_PAIR, CANDLE_TIMEFRAME, CANDLE_LIMIT, TRADE_AMOUNT_USDT,
)

BASE_URL = "https://fapi.bitunix.com"

# Map standard timeframe strings → Bitunix granularity values
TIMEFRAME_MAP = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "1440",
}


def _symbol(pair: str) -> str:
    """Convert 'BTC/USDT' → 'BTCUSDT'."""
    return pair.replace("/", "")


def _get(path: str, params: dict | None = None) -> dict:
    url = BASE_URL + path
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"Bitunix API error {data.get('code')}: {data.get('msg')}")
    return data


def _sign_request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """Build signed headers for private endpoints."""
    ts = str(int(time.time() * 1000))
    query = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    body_str = str(body or "")
    msg = ts + EXCHANGE_API_KEY + query + body_str
    signature = hmac.new(EXCHANGE_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "api-key": EXCHANGE_API_KEY,
        "sign": signature,
        "timestamp": ts,
        "Content-Type": "application/json",
    }


# ── Public interface (mirrors exchange.py) ──────────────────────────────────

class BitunixExchange:
    """Thin wrapper that mimics the ccxt.Exchange surface used by bot.py."""
    pass


def get_exchange(dry_run: bool = True) -> BitunixExchange:
    return BitunixExchange()


def fetch_ohlcv(exchange: BitunixExchange) -> pd.DataFrame:
    granularity = TIMEFRAME_MAP.get(CANDLE_TIMEFRAME, "15")
    data = _get("/api/v1/market/kline", {
        "symbol": _symbol(TRADING_PAIR),
        "granularity": granularity,
        "limit": CANDLE_LIMIT,
    })
    candles = data["data"]
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.apply(pd.to_numeric, errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_ticker(exchange: BitunixExchange) -> dict:
    data = _get("/api/v1/market/ticker", {"symbol": _symbol(TRADING_PAIR)})
    t = data["data"]
    return {
        "last": float(t["lastPrice"]),
        "high": float(t.get("highPrice", 0)),
        "low": float(t.get("lowPrice", 0)),
        "percentage": float(t.get("priceChangePercent", 0)),
        "quoteVolume": float(t.get("quoteVolume", t.get("volume", 0))),
    }


def fetch_balance(exchange: BitunixExchange) -> dict:
    base, quote = TRADING_PAIR.split("/")
    if not (EXCHANGE_API_KEY and EXCHANGE_SECRET):
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}
    try:
        path = "/api/v1/account/assets"
        headers = _sign_request("GET", path)
        resp = requests.get(BASE_URL + path, headers=headers, timeout=10)
        resp.raise_for_status()
        assets = {a["coin"]: float(a["available"]) for a in resp.json().get("data", [])}
        return {
            "base": assets.get(base, 0.0),
            "quote": assets.get(quote, 0.0),
            "base_currency": base,
            "quote_currency": quote,
        }
    except Exception:
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}


def place_market_order(exchange: BitunixExchange, side: str, amount_usdt: float, ticker: dict) -> dict:
    price = ticker["last"]
    qty = round(amount_usdt / price, 6)
    path = "/api/v1/order"
    body = {
        "symbol": _symbol(TRADING_PAIR),
        "side": side.upper(),
        "orderType": "MARKET",
        "qty": str(qty),
    }
    headers = _sign_request("POST", path, body=body)
    resp = requests.post(BASE_URL + path, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
