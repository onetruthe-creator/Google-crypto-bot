"""
Ladybug Executable-Trade Validator — 24-gate fail-closed filter.

All 24 gates must pass for passed=True.  Any gate that cannot be evaluated
(missing / None input) fails-closed, returning passed=False.

Gate summary
------------
 1  Admission: status == CONFIRMED_ANALYSIS and admitted == True
 2  Score: effective_score >= 82
 3  Direction: direction in ("LONG", "SHORT")
 4  1-hour momentum cap: |move_1h_pct| <= 8.0
 5  ATR guard: 0.10 <= atr_pct <= 6.0
 6  Breakout level: breakout_level_price is not None and > 0
 7  Retest zone: retest_zone_low and retest_zone_high both > 0, low < high
 8  Retest completion: retest_confirmed is True
 9  Confirmation candle: confirmation_candle_closed is True
10  Orientation: LONG: stop < entry <= tp1; SHORT: tp1 <= entry < stop
11  Reward-risk: reward_risk >= Decimal("2.0")
12  Chase boundary: |entry_trigger - breakout_level_price| <= 0.25 * atr_15m_price
13  Funding rate: |funding_rate| < 0.0015
14  Relative volume: relative_volume >= 1.5
15  Leverage safety: stop_precedes_liquidation == True
16  Leverage cap: suggested_leverage <= 10
17  Decision not SKIP: risk_decision != "SKIP"
18  Quote volume: quote_volume_24h >= 20_000_000.0
19  24-hour change cap: -15.0 <= change_24h_pct <= 15.0
20  Sentiment non-negative: sentiment_score >= 0.0
21  Opposing-score gap: effective_score - opposing_score >= 10
22  Funding available: funding_available is True
23  Cooldown: same alert_id not fired within cooldown_seconds
24  Enable flag: LADYBUG_EXECUTABLE_ALERTS_ENABLED env var == "1"
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ExecutableSetupInput:
    # Gate 1 — admission
    admission_status: Optional[str] = None       # "CONFIRMED_ANALYSIS"
    admission_admitted: Optional[bool] = None

    # Gate 2 — score
    effective_score: Optional[float] = None      # >= 82

    # Gate 3 — direction
    direction: Optional[str] = None              # "LONG" | "SHORT"

    # Gate 4 — 1h momentum
    move_1h_pct: Optional[float] = None          # abs <= 8.0

    # Gate 5 — ATR
    atr_pct: Optional[float] = None              # 0.10 <= x <= 6.0

    # Gates 6-9 — breakout / retest / confirmation (missing in current DeepSetup)
    breakout_level_price: Optional[float] = None
    retest_zone_low: Optional[float] = None
    retest_zone_high: Optional[float] = None
    retest_confirmed: Optional[bool] = None
    confirmation_candle_closed: Optional[bool] = None

    # Gate 10 — orientation price relationship
    entry_trigger: Optional[float] = None
    take_profit_1: Optional[float] = None
    stop_loss: Optional[float] = None

    # Gate 11 — reward-risk
    reward_risk: Optional[Decimal] = None        # >= 2.0

    # Gate 12 — chase boundary
    atr_15m_price: Optional[float] = None        # for 0.25*ATR_15m distance from entry

    # Gate 13 — funding rate
    funding_rate: Optional[float] = None         # abs < 0.0015

    # Gate 14 — relative volume
    relative_volume: Optional[float] = None      # >= 1.5

    # Gate 15 — liquidation safety
    stop_precedes_liquidation: Optional[bool] = None

    # Gate 16 — leverage cap
    suggested_leverage: Optional[int] = None     # <= 10

    # Gate 17 — risk decision
    risk_decision: Optional[str] = None          # != "SKIP"

    # Gate 18 — quote volume
    quote_volume_24h: Optional[float] = None     # >= 20_000_000

    # Gate 19 — 24h change cap
    change_24h_pct: Optional[float] = None       # -15 <= x <= 15

    # Gate 20 — sentiment
    sentiment_score: Optional[float] = None      # >= 0.0

    # Gate 21 — opposing score gap
    opposing_score: Optional[float] = None       # effective_score - opposing_score >= 10

    # Gate 22 — funding available
    funding_available: Optional[bool] = None

    # Gate 23 — cooldown dedup (passed in as bool from delivery layer)
    within_cooldown: bool = False                 # True = duplicate in window → fail

    # Alert identity
    symbol: Optional[str] = None
    scan_timestamp: Optional[datetime] = None    # for alert ID


@dataclass(frozen=True)
class ExecutableValidatorResult:
    passed: bool
    alert_id: str                                # always computed; empty string on bad inputs
    failure_reasons: tuple[str, ...]


# ---------------------------------------------------------------------------
# Alert-ID computation
# ---------------------------------------------------------------------------

def _fmt_price(v: float) -> str:
    return f"{v:.8f}"


def compute_alert_id(
    *,
    symbol: str,
    direction: str,
    entry_trigger: float,
    stop_loss: float,
    take_profit_1: float,
    scan_timestamp: datetime,
) -> str:
    raw = (
        f"{symbol}|{direction}|{_fmt_price(entry_trigger)}"
        f"|{_fmt_price(stop_loss)}|{_fmt_price(take_profit_1)}"
        f"|{scan_timestamp.isoformat()}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16].upper()
    return f"LB_{digest}"


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_executable_setup(inp: ExecutableSetupInput) -> ExecutableValidatorResult:
    reasons: list[str] = []

    # Build alert_id when we have enough info
    alert_id = ""
    if (
        inp.symbol
        and inp.direction
        and inp.entry_trigger is not None
        and inp.stop_loss is not None
        and inp.take_profit_1 is not None
        and inp.scan_timestamp is not None
    ):
        try:
            alert_id = compute_alert_id(
                symbol=inp.symbol,
                direction=inp.direction,
                entry_trigger=inp.entry_trigger,
                stop_loss=inp.stop_loss,
                take_profit_1=inp.take_profit_1,
                scan_timestamp=inp.scan_timestamp,
            )
        except Exception:
            alert_id = ""

    # --- Gate 1: Admission ---
    if inp.admission_status is None or inp.admission_admitted is None:
        reasons.append("GATE1_FAIL: admission fields missing")
    elif inp.admission_status != "CONFIRMED_ANALYSIS" or not inp.admission_admitted:
        reasons.append(
            f"GATE1_FAIL: admission_status={inp.admission_status!r} admitted={inp.admission_admitted}"
        )

    # --- Gate 2: Score ---
    if inp.effective_score is None:
        reasons.append("GATE2_FAIL: effective_score missing")
    elif inp.effective_score < 82:
        reasons.append(f"GATE2_FAIL: effective_score={inp.effective_score:.1f} < 82")

    # --- Gate 3: Direction ---
    if inp.direction is None:
        reasons.append("GATE3_FAIL: direction missing")
    elif inp.direction not in ("LONG", "SHORT"):
        reasons.append(f"GATE3_FAIL: direction={inp.direction!r} not LONG|SHORT")

    # --- Gate 4: 1h momentum cap ---
    if inp.move_1h_pct is None:
        reasons.append("GATE4_FAIL: move_1h_pct missing")
    elif abs(inp.move_1h_pct) > 8.0:
        reasons.append(f"GATE4_FAIL: |move_1h_pct|={abs(inp.move_1h_pct):.2f} > 8.0")

    # --- Gate 5: ATR guard ---
    if inp.atr_pct is None:
        reasons.append("GATE5_FAIL: atr_pct missing")
    elif not (0.10 <= inp.atr_pct <= 6.0):
        reasons.append(f"GATE5_FAIL: atr_pct={inp.atr_pct:.3f} not in [0.10, 6.0]")

    # --- Gate 6: Breakout level ---
    if inp.breakout_level_price is None:
        reasons.append("GATE6_FAIL: breakout_level_price missing (not in DeepSetup yet)")
    elif inp.breakout_level_price <= 0:
        reasons.append(f"GATE6_FAIL: breakout_level_price={inp.breakout_level_price} <= 0")

    # --- Gate 7: Retest zone ---
    if inp.retest_zone_low is None or inp.retest_zone_high is None:
        reasons.append("GATE7_FAIL: retest_zone_low/high missing (not in DeepSetup yet)")
    elif inp.retest_zone_low <= 0 or inp.retest_zone_high <= 0:
        reasons.append("GATE7_FAIL: retest_zone prices must be > 0")
    elif inp.retest_zone_low >= inp.retest_zone_high:
        reasons.append(
            f"GATE7_FAIL: retest_zone_low={inp.retest_zone_low} >= retest_zone_high={inp.retest_zone_high}"
        )

    # --- Gate 8: Retest completion ---
    if inp.retest_confirmed is None:
        reasons.append("GATE8_FAIL: retest_confirmed missing (not in DeepSetup yet)")
    elif not inp.retest_confirmed:
        reasons.append("GATE8_FAIL: retest_confirmed=False")

    # --- Gate 9: Confirmation candle ---
    if inp.confirmation_candle_closed is None:
        reasons.append("GATE9_FAIL: confirmation_candle_closed missing (not in DeepSetup yet)")
    elif not inp.confirmation_candle_closed:
        reasons.append("GATE9_FAIL: confirmation_candle_closed=False")

    # --- Gate 10: Price orientation ---
    direction_known = inp.direction in ("LONG", "SHORT")
    prices_present = (
        inp.entry_trigger is not None
        and inp.take_profit_1 is not None
        and inp.stop_loss is not None
    )
    if not prices_present:
        reasons.append("GATE10_FAIL: entry_trigger/take_profit_1/stop_loss missing")
    elif direction_known:
        et, tp1, sl = inp.entry_trigger, inp.take_profit_1, inp.stop_loss
        if inp.direction == "LONG":
            if not (sl < et <= tp1):
                reasons.append(
                    f"GATE10_FAIL: LONG orientation violated stop={sl} entry={et} tp1={tp1}"
                )
        else:  # SHORT
            if not (tp1 <= et < sl):
                reasons.append(
                    f"GATE10_FAIL: SHORT orientation violated tp1={tp1} entry={et} stop={sl}"
                )

    # --- Gate 11: Reward-risk ---
    if inp.reward_risk is None:
        reasons.append("GATE11_FAIL: reward_risk missing")
    else:
        try:
            rr = Decimal(inp.reward_risk)
            if rr < Decimal("2.0"):
                reasons.append(f"GATE11_FAIL: reward_risk={rr} < 2.0")
        except Exception:
            reasons.append(f"GATE11_FAIL: reward_risk={inp.reward_risk!r} not numeric")

    # --- Gate 12: Chase boundary ---
    if inp.entry_trigger is None or inp.breakout_level_price is None or inp.atr_15m_price is None:
        reasons.append("GATE12_FAIL: entry_trigger/breakout_level_price/atr_15m_price missing")
    else:
        chase_limit = 0.25 * inp.atr_15m_price
        distance = abs(inp.entry_trigger - inp.breakout_level_price)
        if distance > chase_limit:
            reasons.append(
                f"GATE12_FAIL: entry chased {distance:.6f} > 0.25*ATR_15m={chase_limit:.6f}"
            )

    # --- Gate 13: Funding rate ---
    if inp.funding_rate is None:
        reasons.append("GATE13_FAIL: funding_rate missing")
    elif abs(inp.funding_rate) >= 0.0015:
        reasons.append(f"GATE13_FAIL: |funding_rate|={abs(inp.funding_rate):.6f} >= 0.0015")

    # --- Gate 14: Relative volume ---
    if inp.relative_volume is None:
        reasons.append("GATE14_FAIL: relative_volume missing")
    elif inp.relative_volume < 1.5:
        reasons.append(f"GATE14_FAIL: relative_volume={inp.relative_volume:.2f} < 1.5")

    # --- Gate 15: Liquidation safety ---
    if inp.stop_precedes_liquidation is None:
        reasons.append("GATE15_FAIL: stop_precedes_liquidation missing")
    elif not inp.stop_precedes_liquidation:
        reasons.append("GATE15_FAIL: stop_precedes_liquidation=False")

    # --- Gate 16: Leverage cap ---
    if inp.suggested_leverage is None:
        reasons.append("GATE16_FAIL: suggested_leverage missing")
    elif inp.suggested_leverage > 10:
        reasons.append(f"GATE16_FAIL: suggested_leverage={inp.suggested_leverage} > 10")

    # --- Gate 17: Risk decision ---
    if inp.risk_decision is None:
        reasons.append("GATE17_FAIL: risk_decision missing")
    elif inp.risk_decision == "SKIP":
        reasons.append("GATE17_FAIL: risk_decision=SKIP")

    # --- Gate 18: Quote volume ---
    if inp.quote_volume_24h is None:
        reasons.append("GATE18_FAIL: quote_volume_24h missing")
    elif inp.quote_volume_24h < 20_000_000.0:
        reasons.append(f"GATE18_FAIL: quote_volume_24h={inp.quote_volume_24h:.0f} < 20,000,000")

    # --- Gate 19: 24h change cap ---
    if inp.change_24h_pct is None:
        reasons.append("GATE19_FAIL: change_24h_pct missing")
    elif not (-15.0 <= inp.change_24h_pct <= 15.0):
        reasons.append(f"GATE19_FAIL: change_24h_pct={inp.change_24h_pct:.2f} outside [-15, 15]")

    # --- Gate 20: Sentiment ---
    if inp.sentiment_score is None:
        reasons.append("GATE20_FAIL: sentiment_score missing")
    elif inp.sentiment_score < 0.0:
        reasons.append(f"GATE20_FAIL: sentiment_score={inp.sentiment_score:.3f} < 0")

    # --- Gate 21: Opposing-score gap ---
    if inp.effective_score is None or inp.opposing_score is None:
        reasons.append("GATE21_FAIL: effective_score or opposing_score missing")
    else:
        gap = inp.effective_score - inp.opposing_score
        if gap < 10:
            reasons.append(
                f"GATE21_FAIL: score gap={gap:.1f} < 10 "
                f"(eff={inp.effective_score:.1f} opp={inp.opposing_score:.1f})"
            )

    # --- Gate 22: Funding available ---
    if inp.funding_available is None:
        reasons.append("GATE22_FAIL: funding_available missing")
    elif not inp.funding_available:
        reasons.append("GATE22_FAIL: funding_available=False")

    # --- Gate 23: Cooldown dedup ---
    if inp.within_cooldown:
        reasons.append(f"GATE23_FAIL: alert_id {alert_id!r} already sent within cooldown window")

    # --- Gate 24: Enable flag ---
    enabled = os.environ.get("LADYBUG_EXECUTABLE_ALERTS_ENABLED", "0")
    if enabled != "1":
        reasons.append(
            f"GATE24_FAIL: LADYBUG_EXECUTABLE_ALERTS_ENABLED={enabled!r} (must be '1')"
        )

    return ExecutableValidatorResult(
        passed=len(reasons) == 0,
        alert_id=alert_id,
        failure_reasons=tuple(reasons),
    )
