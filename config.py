import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "kraken")
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET = os.getenv("EXCHANGE_SECRET", "")
TRADING_PAIR = os.getenv("TRADING_PAIR", "BTC/USDT")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "100"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

CANDLE_TIMEFRAME = "15m"
CANDLE_LIMIT = 96  # 24 hours of 15m candles

CLAUDE_MODEL = "claude-opus-5"
