# Google Crypto Bot

AI-powered cryptocurrency trading bot using **Anthropic Claude** for market analysis.

> Migrated from Google Gemini (`gemini-3.5-flash`) to **Claude** (`claude-opus-5`) after Gemini prepayment credits were depleted.

## Features

- Real-time OHLCV candle data from any CCXT-supported exchange (Binance, Coinbase, Kraken, …)
- Technical indicators: RSI, MACD, Bollinger Bands, EMA-20/50, volume ratio
- Claude analyzes indicators + recent price action and returns a structured JSON decision
- Adaptive thinking enabled — Claude reasons before deciding
- Dry-run mode (default on) — logs trade signals without placing real orders
- Configurable check interval via scheduler

## Quick Start

```bash
# 1. Clone the repo and enter the directory
git clone https://github.com/onetruthe-creator/Google-crypto-bot.git
cd Google-crypto-bot

# 2. One-command setup (creates .venv, installs deps, copies .env)
bash setup.sh

# 3. Edit .env and fill in your ANTHROPIC_API_KEY and exchange credentials
nano .env   # or: code .env / vim .env

# 4. Run the bot
.venv/bin/python bot.py
```

> **Debian/Ubuntu users:** do not use `pip install` directly — use the `setup.sh` script above,
> which creates an isolated virtual environment and avoids the externally-managed-environment error.
> Use `.venv/bin/python` (not `python` or `python3`) to run the bot.

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required) |
| `EXCHANGE_ID` | `binance` | Any CCXT exchange ID |
| `EXCHANGE_API_KEY` | — | Exchange API key |
| `EXCHANGE_SECRET` | — | Exchange secret |
| `TRADING_PAIR` | `BTC/USDT` | Market to trade |
| `TRADE_AMOUNT_USDT` | `100` | Quote amount per trade |
| `DRY_RUN` | `true` | Paper-trade only when `true` |
| `CHECK_INTERVAL_MINUTES` | `15` | How often the bot runs a cycle |

## Architecture

```
bot.py          — orchestration, scheduling, order execution
analyzer.py     — Claude API call: technical analysis → buy/sell/hold decision
exchange.py     — CCXT wrapper: OHLCV, ticker, balance, market orders
config.py       — environment variable loading
```

## Trading Logic

Each cycle:
1. Fetch 96 × 15-minute candles (24 hours of data)
2. Compute RSI-14, MACD, Bollinger Bands, EMA-20/50, volume ratio
3. Send indicators + recent price action to Claude (`claude-opus-5`)
4. Claude returns `{action, confidence, reasoning, risk_level, key_signals}`
5. Execute if `action ∈ {buy, sell}`, `confidence ≥ 0.65`, and `risk_level ≠ high`

## Disclaimer

This is an educational project. Cryptocurrency trading carries significant financial risk. Do not trade with funds you cannot afford to lose.
