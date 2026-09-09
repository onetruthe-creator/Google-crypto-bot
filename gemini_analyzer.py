"""
Google Gemini fallback analyzer.
Called automatically when Claude quota is exhausted for the month.
"""

import json
import google.generativeai as genai
import pandas as pd
from config import GEMINI_API_KEY, GEMINI_MODEL, TRADING_PAIR


def analyze_market_gemini(df: pd.DataFrame, ticker: dict, balance: dict, indicators: dict, candles: list) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set — cannot use Gemini fallback.")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    current_price = ticker["last"]
    market_data = {
        "pair": TRADING_PAIR,
        "current_price": current_price,
        "24h_change_pct": round(ticker.get("percentage", 0.0), 2),
        "24h_high": ticker.get("high", 0),
        "24h_low": ticker.get("low", 0),
        "24h_volume": round(ticker.get("quoteVolume", 0), 2),
        "indicators": indicators,
        "recent_candles": candles,
        "wallet": balance,
    }

    prompt = (
        "You are an expert cryptocurrency trading analyst. "
        "Analyze the following market data and return a JSON trading decision with these exact fields:\n"
        "  action: 'buy' | 'sell' | 'hold'\n"
        "  confidence: 0.0-1.0\n"
        "  reasoning: concise explanation (max 3 sentences)\n"
        "  risk_level: 'low' | 'medium' | 'high'\n"
        "  key_signals: list of up to 5 technical signals that drove the decision\n\n"
        "Base your decision strictly on technical indicators and price action. "
        "Never reference fundamentals or news. "
        "Only recommend 'buy' or 'sell' when confidence >= 0.65. "
        "Return valid JSON only — no markdown fences, no extra text.\n\n"
        f"Market data:\n{json.dumps(market_data, indent=2)}"
    )

    response = model.generate_content(prompt)
    raw_text = response.text.strip()

    # Strip markdown fences if Gemini adds them anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        decision = json.loads(raw_text)
    except json.JSONDecodeError:
        decision = {"action": "hold", "confidence": 0.0, "reasoning": "Gemini parse error", "risk_level": "high", "key_signals": []}

    decision["current_price"] = current_price
    decision["indicators"] = indicators
    return decision
