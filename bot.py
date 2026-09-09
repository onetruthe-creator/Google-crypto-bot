#!/usr/bin/env python3
"""
Google Crypto Bot — AI-powered cryptocurrency trading bot using Claude (Anthropic).

Replaces: google/gemini-3.5-flash (credits depleted)
Now uses: Anthropic Claude (claude-opus-5) for market analysis, Gemini as fallback
"""

import time
import logging

import anthropic
import schedule

import config
from coingecko_data import fetch_ohlcv, fetch_ticker
from position_manager import check_exit, open_position, close_position, get_position
import telegram_notify as tg

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


def _execute_order(exchange, action: str, ticker: dict) -> bool:
    if config.DRY_RUN:
        log.info("[DRY RUN] Would execute %s %.2f USDT @ $%.2f",
                 action.upper(), config.TRADE_AMOUNT_USDT, ticker["last"])
        return True
    try:
        order = place_market_order(exchange, action, config.TRADE_AMOUNT_USDT, ticker)
        log.info("Order executed: %s", order)
        return True
    except Exception as exc:
        log.error("Order failed: %s", exc)
        tg.notify_error("Order execution", str(exc))
        return False


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
        tg.notify_error("Data fetch", str(exc))
        return

    current_price = ticker["last"]
    log.info(
        "Price: $%.2f %s | 24h change: %+.2f%% | Balance: %.4f %s / %.2f %s",
        current_price, config.TRADING_PAIR,
        ticker.get("percentage", 0),
        balance["base"], balance["base_currency"],
        balance["quote"], balance["quote_currency"],
    )

    # ── Stop-loss / take-profit check ────────────────────────────────────────
    exit_reason = check_exit(current_price)
    if exit_reason:
        log.info("Exiting position: %s", exit_reason.replace("_", "-").upper())
        pos = get_position()
        if _execute_order(exchange, "sell", ticker):
            close_position()
            tg.notify_trade(
                action="sell",
                price=current_price,
                amount_usdt=pos["amount_usdt"],
                confidence=1.0,
                reasoning=f"Automatic exit: {exit_reason.replace('_', '-')}",
                engine="risk-manager",
                dry_run=config.DRY_RUN,
            )
        log.info("=== Cycle complete ===\n")
        return

    # ── AI analysis ──────────────────────────────────────────────────────────
    try:
        decision = analyze_market(client, df, ticker, balance)
    except Exception as exc:
        log.error("Analysis error: %s", exc)
        tg.notify_error("AI analysis", str(exc))
        return

    action = decision.get("action", "hold")
    confidence = decision.get("confidence", 0.0)
    risk = decision.get("risk_level", "high")
    reasoning = decision.get("reasoning", "")
    signals = decision.get("key_signals", [])
    engine = decision.get("ai_engine", "claude")

    log.info("Decision: %s | Confidence: %.0f%% | Risk: %s | Engine: %s",
             action.upper(), confidence * 100, risk, engine)
    log.info("Reasoning: %s", reasoning)
    if signals:
        log.info("Key signals: %s", " | ".join(signals))

    # ── Trade execution ───────────────────────────────────────────────────────
    if action in ("buy", "sell") and confidence >= 0.65 and risk != "high":
        if _execute_order(exchange, action, ticker):
            if action == "buy":
                open_position("buy", current_price, config.TRADE_AMOUNT_USDT)
            else:
                close_position()
            tg.notify_trade(action, current_price, config.TRADE_AMOUNT_USDT,
                            confidence, reasoning, engine, config.DRY_RUN)
    else:
        log.info("No trade (action=%s, confidence=%.2f, risk=%s)", action, confidence, risk)
        tg.notify_hold(current_price, confidence, reasoning, signals, engine)

    log.info("=== Cycle complete ===\n")


def main() -> None:
    log.info("Starting Google Crypto Bot")
    log.info("AI engine: Anthropic Claude (%s) | Gemini fallback: %s",
             config.CLAUDE_MODEL, "enabled" if config.GEMINI_API_KEY else "disabled")
    log.info("Trading pair: %s | Dry run: %s | SL: %.1f%% | TP: %.1f%%",
             config.TRADING_PAIR, config.DRY_RUN,
             config.STOP_LOSS_PCT, config.TAKE_PROFIT_PCT)

    if not config.ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        raise SystemExit(1)

    tg.init(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    tg.notify_startup(config.TRADING_PAIR, config.DRY_RUN, config.CHECK_INTERVAL_MINUTES)
    run_cycle(client)

    schedule.every(config.CHECK_INTERVAL_MINUTES).minutes.do(run_cycle, client=client)
    log.info("Scheduler running — checking every %d minutes. Press Ctrl+C to stop.",
             config.CHECK_INTERVAL_MINUTES)

    try:
        while True:
            schedule.run_pending()
            time.sleep(10)
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
