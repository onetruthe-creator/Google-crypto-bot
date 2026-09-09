"""
Telegram notification layer.
Sends alerts for trade signals, high-confidence holds, and errors.
Silently skips if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set.
"""

import logging
import requests
from config import TRADING_PAIR

log = logging.getLogger(__name__)

_TOKEN: str = ""
_CHAT_ID: str = ""


def init(token: str, chat_id: str) -> None:
    global _TOKEN, _CHAT_ID
    _TOKEN = token
    _CHAT_ID = chat_id


def _send(text: str) -> None:
    if not (_TOKEN and _CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)


def notify_trade(action: str, price: float, amount_usdt: float, confidence: float,
                 reasoning: str, engine: str, dry_run: bool) -> None:
    emoji = "🟢" if action == "buy" else "🔴"
    mode = "[DRY RUN] " if dry_run else ""
    _send(
        f"{emoji} <b>{mode}{action.upper()} signal — {TRADING_PAIR}</b>\n"
        f"Price: <b>${price:,.2f}</b>\n"
        f"Amount: ${amount_usdt:.2f} USDT\n"
        f"Confidence: {confidence*100:.0f}%\n"
        f"Engine: {engine}\n"
        f"Reasoning: {reasoning}"
    )


def notify_hold(price: float, confidence: float, reasoning: str, signals: list[str], engine: str) -> None:
    if confidence < 0.55:
        return  # Only notify on notable holds
    _send(
        f"⏸ <b>HOLD — {TRADING_PAIR}</b>\n"
        f"Price: <b>${price:,.2f}</b>\n"
        f"Confidence: {confidence*100:.0f}%\n"
        f"Engine: {engine}\n"
        f"Reasoning: {reasoning}\n"
        f"Signals: {' | '.join(signals[:3])}"
    )


def notify_error(context: str, error: str) -> None:
    _send(f"⚠️ <b>Bot error — {context}</b>\n{error}")


def notify_startup(pair: str, dry_run: bool, interval_min: int) -> None:
    mode = "DRY RUN 🧪" if dry_run else "LIVE TRADING 🚀"
    _send(
        f"🤖 <b>Google Crypto Bot started</b>\n"
        f"Pair: {pair}\n"
        f"Mode: {mode}\n"
        f"Interval: every {interval_min} minutes"
    )
