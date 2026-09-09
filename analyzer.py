import json
import anthropic
import pandas as pd
import ta
from config import CLAUDE_MODEL, TRADING_PAIR


def _compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    volume = df["volume"]

    rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
    macd_obj = ta.trend.MACD(close)
    macd = macd_obj.macd().iloc[-1]
    macd_signal = macd_obj.macd_signal().iloc[-1]
    macd_hist = macd_obj.macd_diff().iloc[-1]
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]
    bb_mid = bb.bollinger_mavg().iloc[-1]
    ema_20 = ta.trend.EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema_50 = ta.trend.EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    volume_sma = volume.rolling(20).mean().iloc[-1]

    return {
        "rsi_14": round(rsi, 2),
        "macd": round(macd, 4),
        "macd_signal": round(macd_signal, 4),
        "macd_histogram": round(macd_hist, 4),
        "bollinger_upper": round(bb_upper, 2),
        "bollinger_mid": round(bb_mid, 2),
        "bollinger_lower": round(bb_lower, 2),
        "ema_20": round(ema_20, 2),
        "ema_50": round(ema_50, 2),
        "volume_vs_sma": round(volume.iloc[-1] / volume_sma, 2),
    }


def _recent_candles_summary(df: pd.DataFrame, n: int = 10) -> list[dict]:
    recent = df.tail(n).copy()
    return [
        {
            "time": str(row["timestamp"]),
            "open": round(row["open"], 2),
            "high": round(row["high"], 2),
            "low": round(row["low"], 2),
            "close": round(row["close"], 2),
            "volume": round(row["volume"], 4),
        }
        for _, row in recent.iterrows()
    ]


def analyze_market(client: anthropic.Anthropic, df: pd.DataFrame, ticker: dict, balance: dict) -> dict:
    indicators = _compute_indicators(df)
    candles = _recent_candles_summary(df)
    current_price = ticker["last"]
    change_24h = ticker.get("percentage", 0.0)

    market_data = {
        "pair": TRADING_PAIR,
        "current_price": current_price,
        "24h_change_pct": round(change_24h, 2),
        "24h_high": ticker.get("high", 0),
        "24h_low": ticker.get("low", 0),
        "24h_volume": round(ticker.get("quoteVolume", 0), 2),
        "indicators": indicators,
        "recent_candles_15m": candles,
        "wallet": balance,
    }

    system_prompt = (
        "You are an expert cryptocurrency trading analyst. "
        "Analyze market data and return a JSON trading decision with these exact fields:\n"
        "  action: 'buy' | 'sell' | 'hold'\n"
        "  confidence: 0.0-1.0\n"
        "  reasoning: concise explanation (max 3 sentences)\n"
        "  risk_level: 'low' | 'medium' | 'high'\n"
        "  key_signals: list of up to 5 technical signals that drove the decision\n\n"
        "Base your decision strictly on technical indicators and price action. "
        "Never reference fundamentals or news. "
        "Only recommend 'buy' or 'sell' when confidence >= 0.65. "
        "Return valid JSON only — no markdown fences, no extra text."
    )

    user_prompt = f"Analyze this market data and provide a trading decision:\n\n{json.dumps(market_data, indent=2)}"

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        response = stream.get_final_message()

    raw_text = next(
        (block.text for block in response.content if hasattr(block, "text")),
        "{}",
    )

    try:
        decision = json.loads(raw_text)
    except json.JSONDecodeError:
        decision = {"action": "hold", "confidence": 0.0, "reasoning": "Parse error", "risk_level": "high", "key_signals": []}

    decision["current_price"] = current_price
    decision["indicators"] = indicators
    return decision
