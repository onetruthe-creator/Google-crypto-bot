#!/usr/bin/env python3
"""
Google Crypto Bot — AI-powered cryptocurrency trading bot using Claude (Anthropic).

Replaces: google/gemini-3.5-flash (credits depleted)
Now uses: Anthropic Claude (claude-opus-5) for market analysis
"""

import time
import logging
from datetime import datetime

import anthropic
import schedule

import config
from coingecko_data import fetch_ohlcv, fetch_ticker

if config.EXCHANGE_ID.lower() == "bitunix":
    from bitunix_exchange import get_exchange, fetch_balance, place_market_order
else:
    from exchange import get_exchange, fetch_balance, place_market_order

from analyzer import analyze_market

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def run_cycle(client: anthropic.Anthropic) -> None:
    log.info("=== Starting analysis cycle ===")

    try:
        log.info("Fetching market data from CoinGecko ...")
        df = fetch_ohlcv(config.TRADING_PAIR)
        ticker = fetch_ticker(config.TRADING_PAIR)
        exchange = get_exchange(dry_run=config.DRY_RUN)
        balance = fetch_balance(exchange)
    except Exception as exc:
        log.error("Data fetch error: %s", exc)
        return

    log.info(
        "Price: %s %s | 24h change: %+.2f%% | Balance: %.4f %s / %.2f %s",
        ticker["last"],
        config.TRADING_PAIR,
        ticker.get("percentage", 0),
        balance["base"],
        balance["base_currency"],
        balance["quote"],
        balance["quote_currency"],
    )

    try:
        decision = analyze_market(client, df, ticker, balance)
    except Exception as exc:
        log.error("Claude analysis error: %s", exc)
        return

    action = decision.get("action", "hold")
    confidence = decision.get("confidence", 0.0)
    risk = decision.get("risk_level", "high")
    reasoning = decision.get("reasoning", "")
    signals = decision.get("key_signals", [])

    engine = decision.get("ai_engine", "claude")
    log.info(
        "Decision: %s | Confidence: %.0f%% | Risk: %s | Engine: %s",
        action.upper(),
        confidence * 100,
        risk,
        engine,
    )
    log.info("Reasoning: %s", reasoning)
    if signals:
        log.info("Key signals: %s", " | ".join(signals))

    if action in ("buy", "sell") and confidence >= 0.65 and risk != "high":
        if config.DRY_RUN:
            log.info("[DRY RUN] Would execute %s %.2f USDT @ %s", action.upper(), config.TRADE_AMOUNT_USDT, ticker["last"])
        else:
            try:
                order = place_market_order(exchange, action, config.TRADE_AMOUNT_USDT, ticker)
                log.info("Order executed: %s", order)
            except Exception as exc:
                log.error("Order failed: %s", exc)
    else:
        log.info("No trade executed (action=%s, confidence=%.2f, risk=%s)", action, confidence, risk)

    log.info("=== Cycle complete ===\n")


def main() -> None:
    log.info("Starting Google Crypto Bot")
    log.info("AI engine: Anthropic Claude (%s)", config.CLAUDE_MODEL)
    log.info("Trading pair: %s | Dry run: %s", config.TRADING_PAIR, config.DRY_RUN)

    if not config.ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        raise SystemExit(1)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    run_cycle(client)

    schedule.every(config.CHECK_INTERVAL_MINUTES).minutes.do(run_cycle, client=client)
    log.info("Scheduler running — checking every %d minutes. Press Ctrl+C to stop.", config.CHECK_INTERVAL_MINUTES)

    try:
        while True:
            schedule.run_pending()
            time.sleep(10)
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
