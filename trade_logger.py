"""
Trade history logger — appends every decision and executed trade to trades.csv.
Nothing is ever deleted; the file grows as a permanent audit trail.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
LOG_FILE = Path("trades.csv")

HEADERS = [
    "timestamp", "pair", "action", "confidence", "risk_level",
    "price", "amount_usdt", "executed", "dry_run",
    "ai_engine", "reasoning", "signals",
]


def _ensure_headers() -> None:
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
        with LOG_FILE.open("w", newline="") as f:
            csv.writer(f).writerow(HEADERS)


def log_decision(
    pair: str,
    action: str,
    confidence: float,
    risk_level: str,
    price: float,
    amount_usdt: float,
    executed: bool,
    dry_run: bool,
    ai_engine: str,
    reasoning: str,
    signals: list[str],
) -> None:
    _ensure_headers()
    try:
        with LOG_FILE.open("a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),
                pair,
                action,
                round(confidence, 4),
                risk_level,
                price,
                amount_usdt,
                executed,
                dry_run,
                ai_engine,
                reasoning,
                " | ".join(signals),
            ])
    except Exception as exc:
        log.warning("Trade log write failed: %s", exc)


def log_exit(pair: str, price: float, amount_usdt: float, reason: str, dry_run: bool) -> None:
    _ensure_headers()
    try:
        with LOG_FILE.open("a", newline="") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),
                pair,
                "sell",
                1.0,
                "exit",
                price,
                amount_usdt,
                True,
                dry_run,
                "risk-manager",
                reason,
                "",
            ])
    except Exception as exc:
        log.warning("Exit log write failed: %s", exc)
