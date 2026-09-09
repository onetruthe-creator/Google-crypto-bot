"""
CoinGecko free API — market data layer (no API key required).
Fetches OHLCV candles and ticker; trading still goes through the exchange.
"""

import time
import requests
import pandas as pd
from config import TRADING_PAIR

BASE_URL = "https://api.coingecko.com/api/v3"

# Map base currency → CoinGecko coin ID
COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "TRX": "tron",
}


def _coin_id(pair: str) -> str:
    base = pair.split("/")[0].upper()
    if base not in COIN_IDS:
        raise ValueError(
            f"No CoinGecko ID for '{base}'. Add it to COIN_IDS in coingecko_data.py. "
            f"Find the ID at https://api.coingecko.com/api/v3/coins/list"
        )
    return COIN_IDS[base]


def _get(path: str, params: dict) -> dict | list:
    resp = requests.get(BASE_URL + path, params=params, timeout=15)
    if resp.status_code == 429:
        time.sleep(60)
        resp = requests.get(BASE_URL + path, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_ohlcv(pair: str = TRADING_PAIR, days: int = 2) -> pd.DataFrame:
    """
    Fetches OHLC candles from CoinGecko.
    Free tier granularity: 1-2 days → 30-minute candles (~96 candles for 2 days).
    Returns a DataFrame with columns: timestamp, open, high, low, close, volume.
    """
    coin = _coin_id(pair)
    raw = _get(f"/coins/{coin}/ohlc", {"vs_currency": "usd", "days": days})
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["volume"] = float("nan")  # OHLC endpoint has no volume; fetched separately below
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Enrich with hourly volume from market_chart
    try:
        chart = _get(f"/coins/{coin}/market_chart", {
            "vs_currency": "usd",
            "days": days,
            "interval": "hourly",
        })
        vol_df = pd.DataFrame(chart["total_volumes"], columns=["timestamp", "volume"])
        vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms")
        # Match each 30m candle to the nearest hourly volume bucket
        df = df.sort_values("timestamp")
        vol_df = vol_df.sort_values("timestamp")
        df = pd.merge_asof(df, vol_df, on="timestamp", direction="nearest", suffixes=("_drop", ""))
        if "volume_drop" in df.columns:
            df = df.drop(columns=["volume_drop"])
    except Exception:
        df["volume"] = 0.0

    return df.reset_index(drop=True)


def fetch_ticker(pair: str = TRADING_PAIR) -> dict:
    """Fetches current price + 24h stats from CoinGecko simple/price endpoint."""
    coin = _coin_id(pair)
    data = _get("/simple/price", {
        "ids": coin,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_high_24h": "true",
        "include_low_24h": "true",
    })
    d = data[coin]
    return {
        "last": d["usd"],
        "high": d.get("usd_24h_high", 0),
        "low": d.get("usd_24h_low", 0),
        "percentage": d.get("usd_24h_change", 0),
        "quoteVolume": d.get("usd_24h_vol", 0),
    }
