import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "bitunix")
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET = os.getenv("EXCHANGE_SECRET", "")
TRADING_PAIR = os.getenv("TRADING_PAIR", "BTC/USDT")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "100"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

CANDLE_TIMEFRAME = "15m"
CANDLE_LIMIT = 96  # 24 hours of 15m candles

# Risk management
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.5"))    # % below entry
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "5.0")) # % above entry

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

CLAUDE_MODEL = "claude-opus-5"

# Gemini fallback (used when Claude quota is exhausted)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
