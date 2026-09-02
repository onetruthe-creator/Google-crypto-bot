from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .detector import Candle, avg_volume, calculate_rsi
from .state import SymbolState, Phase


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]


def check_gates(
    candles: Sequence[Candle],
    state: SymbolState,
    rsi_period: int = 14,
    rsi_max: float = 75.0,
    min_volume_usdt: float = 1_000_000.0,
) -> GateResult:
    reasons: list[str] = []

    if state.phase not in (Phase.REJECTION, Phase.PENDING):
        reasons.append("sequence not yet complete")
        return GateResult(False, reasons)

    curr = candles[-1]
    av = avg_volume(candles[:-1], 20)

    # Gate 1: price still above broken level
    if curr.close <= state.level:
        reasons.append(f"price {curr.close:.4f} not above level {state.level:.4f}")

    # Gate 2: volume on current candle above average
    if curr.volume < av:
        reasons.append(f"current volume {curr.volume:.2f} below average {av:.2f}")

    # Gate 3: RSI not overbought
    rsi = calculate_rsi(candles, rsi_period)
    if rsi > rsi_max:
        reasons.append(f"RSI {rsi:.1f} above max {rsi_max}")

    # Gate 4: 24h volume proxy (last 24 candles if hourly)
    recent_vol_usdt = sum(c.close * c.volume for c in list(candles)[-24:])
    if recent_vol_usdt < min_volume_usdt:
        reasons.append(f"24h volume ${recent_vol_usdt:,.0f} below minimum ${min_volume_usdt:,.0f}")

    passed = len(reasons) == 0
    return GateResult(passed, reasons)


def setup_still_valid(candles: Sequence[Candle], state: SymbolState) -> bool:
    if state.phase in (Phase.NONE, Phase.CONFIRMED, Phase.WITHDRAWN):
        return False
    curr = candles[-1]
    # Setup invalidated if price closes significantly below the broken level
    invalidation_threshold = state.level * 0.995
    return curr.close > invalidation_threshold
