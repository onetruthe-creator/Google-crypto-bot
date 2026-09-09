"""
Position manager — tracks open positions and checks stop-loss / take-profit.
State is persisted to positions.json so the bot survives restarts.
"""

import json
import logging
from pathlib import Path
from config import STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRADING_PAIR

log = logging.getLogger(__name__)
STATE_FILE = Path("positions.json")


def _load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def open_position(side: str, entry_price: float, amount_usdt: float) -> None:
    state = _load()
    state[TRADING_PAIR] = {
        "side": side,
        "entry_price": entry_price,
        "amount_usdt": amount_usdt,
        "stop_loss": round(entry_price * (1 - STOP_LOSS_PCT / 100), 2),
        "take_profit": round(entry_price * (1 + TAKE_PROFIT_PCT / 100), 2),
    }
    _save(state)
    log.info(
        "Position opened: %s @ $%.2f | SL: $%.2f | TP: $%.2f",
        side.upper(), entry_price,
        state[TRADING_PAIR]["stop_loss"],
        state[TRADING_PAIR]["take_profit"],
    )


def close_position() -> None:
    state = _load()
    state.pop(TRADING_PAIR, None)
    _save(state)


def get_position() -> dict | None:
    return _load().get(TRADING_PAIR)


def check_exit(current_price: float) -> str | None:
    """
    Returns 'stop_loss', 'take_profit', or None.
    Caller is responsible for executing the exit order.
    """
    pos = get_position()
    if not pos:
        return None

    if pos["side"] == "buy":
        if current_price <= pos["stop_loss"]:
            log.warning("STOP-LOSS hit: price $%.2f <= SL $%.2f", current_price, pos["stop_loss"])
            return "stop_loss"
        if current_price >= pos["take_profit"]:
            log.info("TAKE-PROFIT hit: price $%.2f >= TP $%.2f", current_price, pos["take_profit"])
            return "take_profit"

    return None
