"""
ladybug_retest_detector.py — Breakout/retest pattern detection for Ladybug.

Identifies whether the current candle series shows a post-breakout retest
of a key level so that Gates 6–9 of the executable-alert pipeline can pass.

Pattern definitions
-------------------
SHORT retest:
  - Price broke DOWN from a prior high (the "breakout level").
  - Price has since bounced back UP toward that level for a retest.
  - Confirmation: the last closed candle is bearish (close < open),
    signalling rejection from the former support-turned-resistance.

LONG retest:
  - Price broke UP from a prior low.
  - Price has since pulled back DOWN toward that level.
  - Confirmation: the last closed candle is bullish (close > open).

Algorithm (using 100×15 m candles)
------------------------------------
1. Take the "lookback slice": candles[SKIP_HEAD : -SKIP_TAIL].
   - SKIP_HEAD = 3 (avoid startup noise)
   - SKIP_TAIL = 8 (exclude the candles representing the current retest approach)
2. SHORT → breakout_level = max close in the lookback slice (peak before drop).
   LONG  → breakout_level = min close in the lookback slice (trough before rise).
3. Retest zone = [breakout_level × (1−buf), breakout_level × (1+buf)].
   buf = min(0.4 × atr_pct, 1.5) / 100  (ATR-scaled, capped at 1.5 %).
4. retest_confirmed  = current price is inside the zone.
5. confirmation_candle_closed = last candle body moves in trade direction.

AUTHORIZATION: NONE — read-only analysis; no exchange orders are placed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


_SKIP_HEAD = 3
_SKIP_TAIL = 8
_MIN_CANDLES = _SKIP_HEAD + _SKIP_TAIL + 10  # at least 21 usable closes


@dataclass(frozen=True)
class RetestDetection:
    breakout_level_price: Optional[float]
    retest_zone_low: Optional[float]
    retest_zone_high: Optional[float]
    retest_confirmed: Optional[bool]
    confirmation_candle_closed: Optional[bool]
    reason: str


def _f(val) -> Optional[float]:
    try:
        v = float(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _no_detection(reason: str) -> RetestDetection:
    return RetestDetection(
        breakout_level_price=None,
        retest_zone_low=None,
        retest_zone_high=None,
        retest_confirmed=None,
        confirmation_candle_closed=None,
        reason=reason,
    )


def detect_retest(
    candles: list,
    *,
    direction: str,
    last_price: float,
    atr_pct: float,
) -> RetestDetection:
    """
    Analyse ``candles`` (list of dicts, oldest-first) and return a
    RetestDetection describing the breakout/retest state.

    Parameters
    ----------
    candles:    Raw candle dicts with at minimum "open" and "close" keys.
    direction:  "LONG" or "SHORT" (from the Ladybug scoring engine).
    last_price: Current close price (last element of the candle series).
    atr_pct:    ATR expressed as a percentage of price (already computed
                by _atr_pct() in analyze_symbol).

    AUTHORIZATION: NONE
    """
    if direction not in ("LONG", "SHORT"):
        return _no_detection("unknown_direction")

    if len(candles) < _MIN_CANDLES:
        return _no_detection("insufficient_candles")

    closes: list[float] = []
    opens: list[float] = []
    for c in candles:
        cv = _f(c.get("close"))
        ov = _f(c.get("open"))
        if cv is not None:
            closes.append(cv)
        if ov is not None:
            opens.append(ov)

    if len(closes) < _MIN_CANDLES:
        return _no_detection("insufficient_valid_closes")

    lookback = closes[_SKIP_HEAD : len(closes) - _SKIP_TAIL]
    if not lookback:
        return _no_detection("lookback_empty")

    if direction == "SHORT":
        breakout_level = max(lookback)
    else:
        breakout_level = min(lookback)

    if breakout_level <= 0:
        return _no_detection("invalid_breakout_level")

    # Zone width: 0.4 × ATR, capped at 1.5 % of the breakout level.
    buf_pct = min(atr_pct * 0.4, 1.5) / 100.0
    zone_low = breakout_level * (1.0 - buf_pct)
    zone_high = breakout_level * (1.0 + buf_pct)

    retest_confirmed: bool = zone_low <= last_price <= zone_high

    # Confirmation candle: the most-recent close must move in the trade direction.
    confirmation_candle_closed: Optional[bool] = None
    if opens and closes:
        last_open = opens[-1] if len(opens) == len(closes) else None
        last_close = closes[-1]
        if last_open is not None and last_open > 0:
            if direction == "SHORT":
                confirmation_candle_closed = last_close < last_open
            else:
                confirmation_candle_closed = last_close > last_open

    return RetestDetection(
        breakout_level_price=breakout_level,
        retest_zone_low=zone_low,
        retest_zone_high=zone_high,
        retest_confirmed=retest_confirmed,
        confirmation_candle_closed=confirmation_candle_closed,
        reason="detected",
    )
