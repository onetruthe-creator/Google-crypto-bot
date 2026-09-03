"""
Ladybug Executable-Alert Formatter.

Produces the exact Telegram message format specified in the Ladybug spec.
Every field is taken directly from the validated inputs — no inference,
no defaults that could mask a missing value.

AUTHORIZATION: NONE — this system is read-only analysis only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sovereign_mission_engine.lb_executable_validator import (
    ExecutableSetupInput,
    ExecutableValidatorResult,
)


_DIRECTION_ARROW = {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT"}


def _pct(v: float, decimals: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def _price(v: float) -> str:
    if v >= 1000:
        return f"{v:,.2f}"
    elif v >= 1:
        return f"{v:.4f}"
    else:
        return f"{v:.8f}"


def _rvol(v: float) -> str:
    return f"{v:.2f}x"


def _lev(v: int) -> str:
    return f"{v}x"


def _rr(v: Decimal) -> str:
    return f"{v:.2f}"


def _fr(v: float) -> str:
    # funding rate as percentage with sign
    pct = v * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.4f}%"


def _score(v: float) -> str:
    return f"{v:.1f}/100"


def format_executable_alert(
    inp: ExecutableSetupInput,
    result: ExecutableValidatorResult,
    *,
    suggested_leverage: Optional[int] = None,
    reward_risk: Optional[Decimal] = None,
) -> str:
    """
    Build the Telegram alert string.  Only call this when result.passed == True.
    Raises ValueError if result.passed is False or required fields are missing.
    """
    if not result.passed:
        raise ValueError(
            f"format_executable_alert called with failed validation: {result.failure_reasons}"
        )

    required = [
        "symbol", "direction", "entry_trigger", "stop_loss", "take_profit_1",
        "effective_score", "atr_pct", "move_1h_pct", "change_24h_pct",
        "relative_volume", "funding_rate",
    ]
    missing = [f for f in required if getattr(inp, f, None) is None]
    if missing:
        raise ValueError(f"format_executable_alert: missing required fields: {missing}")

    lev = suggested_leverage if suggested_leverage is not None else inp.suggested_leverage
    rr = reward_risk if reward_risk is not None else inp.reward_risk

    direction_label = _DIRECTION_ARROW.get(inp.direction, inp.direction)

    lines = [
        "⚡ CONFIRMED_SETUP — EXECUTABLE",
        "",
        f"Symbol    : {inp.symbol}  {direction_label}",
        f"Alert ID  : {result.alert_id}",
        "",
        "— ENTRY ——————————————————————",
        f"Entry     : {_price(inp.entry_trigger)}",
        f"Stop Loss : {_price(inp.stop_loss)}",
        f"Take Profit: {_price(inp.take_profit_1)}",
        f"R:R       : {_rr(rr) if rr is not None else 'N/A'}",
        f"Leverage  : {_lev(lev) if lev is not None else 'N/A'}",
        "",
        "— EVIDENCE ————————————————————",
        f"Score     : {_score(inp.effective_score)}",
        f"ATR       : {_pct(inp.atr_pct)}",
        f"1h move   : {_pct(inp.move_1h_pct)}",
        f"24h change: {_pct(inp.change_24h_pct)}",
        f"Rel. Vol  : {_rvol(inp.relative_volume)}",
        f"Funding   : {_fr(inp.funding_rate)}",
        "",
        "AUTHORIZATION: NONE",
        "Ladybug is read-only analysis. No trade is placed by this system.",
    ]

    return "\n".join(lines)
