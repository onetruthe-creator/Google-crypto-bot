import ccxt
import pandas as pd
from config import (
    EXCHANGE_ID, EXCHANGE_API_KEY, EXCHANGE_SECRET,
    TRADING_PAIR, CANDLE_TIMEFRAME, CANDLE_LIMIT,
)


def get_exchange(dry_run: bool = True) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, EXCHANGE_ID)
    exchange = exchange_class({
        "apiKey": EXCHANGE_API_KEY,
        "secret": EXCHANGE_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if dry_run:
        exchange.set_sandbox_mode(False)
    return exchange


def fetch_ohlcv(exchange: ccxt.Exchange) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(TRADING_PAIR, timeframe=CANDLE_TIMEFRAME, limit=CANDLE_LIMIT)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_ticker(exchange: ccxt.Exchange) -> dict:
    return exchange.fetch_ticker(TRADING_PAIR)


def fetch_balance(exchange: ccxt.Exchange) -> dict:
    base, quote = TRADING_PAIR.split("/")
    # Skip authenticated call when no keys are configured (dry-run / analysis-only mode)
    if not (EXCHANGE_API_KEY and EXCHANGE_SECRET):
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}
    try:
        balance = exchange.fetch_balance()
        return {
            "base": balance["free"].get(base, 0.0),
            "quote": balance["free"].get(quote, 0.0),
            "base_currency": base,
            "quote_currency": quote,
        }
    except ccxt.AuthenticationError:
        return {"base": 0.0, "quote": 0.0, "base_currency": base, "quote_currency": quote}


def place_market_order(exchange: ccxt.Exchange, side: str, amount_usdt: float, ticker: dict) -> dict | None:
    base, quote = TRADING_PAIR.split("/")
    price = ticker["last"]

    if side == "buy":
        amount = amount_usdt / price
    else:
        amount = amount_usdt / price

    order = exchange.create_market_order(TRADING_PAIR, side, amount)
    return order
