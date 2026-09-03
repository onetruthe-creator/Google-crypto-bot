"""
Tests for lb_executable_validator.py — 29 required test cases covering all 24 gates.

All tests run without network access.  The enable flag (Gate 24) is patched
via os.environ so tests do not require the env var to be set in CI.
"""

import os
import unittest
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from decimal import Decimal

os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "1"  # enable for tests unless overridden

from sovereign_mission_engine.lb_executable_validator import (
    ExecutableSetupInput,
    compute_alert_id,
    validate_executable_setup,
)

_TS = datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

GOOD_INPUT = ExecutableSetupInput(
    admission_status="CONFIRMED_ANALYSIS",
    admission_admitted=True,
    effective_score=85.0,
    direction="LONG",
    move_1h_pct=2.0,
    atr_pct=1.5,
    breakout_level_price=100.0,
    retest_zone_low=98.0,
    retest_zone_high=99.5,
    retest_confirmed=True,
    confirmation_candle_closed=True,
    entry_trigger=99.8,
    take_profit_1=104.0,
    stop_loss=97.0,
    reward_risk=Decimal("2.15"),
    atr_15m_price=0.50,       # 0.25 * 0.50 = 0.125; distance 99.8-100.0=0.2 > 0.125 → use price s.t. entry==breakout
    funding_rate=0.0001,
    relative_volume=2.0,
    stop_precedes_liquidation=True,
    suggested_leverage=5,
    risk_decision="TRADE",
    quote_volume_24h=50_000_000.0,
    change_24h_pct=3.0,
    sentiment_score=0.5,
    opposing_score=70.0,
    funding_available=True,
    within_cooldown=False,
    symbol="BTCUSDT",
    scan_timestamp=_TS,
)

# Adjust atr_15m_price so Gate 12 passes: entry=99.8, breakout=100.0, dist=0.2
# 0.25 * atr_15m must be >= 0.2 → atr_15m >= 0.8
GOOD: ExecutableSetupInput = dc_replace(GOOD_INPUT, atr_15m_price=1.0)


def _validate(inp: ExecutableSetupInput):
    return validate_executable_setup(inp)


class TestAlertIdComputation(unittest.TestCase):
    def test_alert_id_prefix(self):
        aid = compute_alert_id(
            symbol="BTCUSDT",
            direction="LONG",
            entry_trigger=99.8,
            stop_loss=97.0,
            take_profit_1=104.0,
            scan_timestamp=_TS,
        )
        self.assertTrue(aid.startswith("LB_"), aid)
        self.assertEqual(len(aid), 19)  # LB_ + 16 hex chars

    def test_alert_id_deterministic(self):
        kwargs = dict(
            symbol="ETHUSDT", direction="SHORT",
            entry_trigger=2000.0, stop_loss=2100.0, take_profit_1=1800.0,
            scan_timestamp=_TS,
        )
        self.assertEqual(compute_alert_id(**kwargs), compute_alert_id(**kwargs))

    def test_alert_id_differs_by_direction(self):
        base = dict(symbol="BTCUSDT", entry_trigger=1.0, stop_loss=0.9, take_profit_1=1.2, scan_timestamp=_TS)
        long_id = compute_alert_id(**base, direction="LONG")
        short_id = compute_alert_id(**base, direction="SHORT")
        self.assertNotEqual(long_id, short_id)


class TestAllGatesPass(unittest.TestCase):
    def test_good_input_passes(self):
        r = _validate(GOOD)
        self.assertTrue(r.passed, r.failure_reasons)
        self.assertEqual(len(r.failure_reasons), 0)
        self.assertTrue(r.alert_id.startswith("LB_"))


class TestGate1Admission(unittest.TestCase):
    def test_wrong_status_fails(self):
        r = _validate(dc_replace(GOOD, admission_status="WAIT_FOR_CONFIRMATION"))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE1" in x for x in r.failure_reasons))

    def test_admitted_false_fails(self):
        r = _validate(dc_replace(GOOD, admission_admitted=False))
        self.assertFalse(r.passed)

    def test_admission_status_none_fails(self):
        r = _validate(dc_replace(GOOD, admission_status=None))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE1" in x for x in r.failure_reasons))


class TestGate2Score(unittest.TestCase):
    def test_score_81_fails(self):
        r = _validate(dc_replace(GOOD, effective_score=81.9))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE2" in x for x in r.failure_reasons))

    def test_score_82_passes(self):
        r = _validate(dc_replace(GOOD, effective_score=82.0))
        self.assertTrue(r.passed, r.failure_reasons)

    def test_score_none_fails(self):
        r = _validate(dc_replace(GOOD, effective_score=None))
        self.assertFalse(r.passed)


class TestGate3Direction(unittest.TestCase):
    def test_invalid_direction_fails(self):
        r = _validate(dc_replace(GOOD, direction="FLAT"))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE3" in x for x in r.failure_reasons))

    def test_none_direction_fails(self):
        r = _validate(dc_replace(GOOD, direction=None))
        self.assertFalse(r.passed)


class TestGate4Momentum(unittest.TestCase):
    def test_exactly_8_passes(self):
        r = _validate(dc_replace(GOOD, move_1h_pct=8.0))
        self.assertTrue(r.passed, r.failure_reasons)

    def test_above_8_fails(self):
        r = _validate(dc_replace(GOOD, move_1h_pct=8.01))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE4" in x for x in r.failure_reasons))

    def test_negative_above_8_fails(self):
        r = _validate(dc_replace(GOOD, move_1h_pct=-8.5))
        self.assertFalse(r.passed)

    def test_none_fails(self):
        r = _validate(dc_replace(GOOD, move_1h_pct=None))
        self.assertFalse(r.passed)


class TestGate5ATR(unittest.TestCase):
    def test_atr_too_low_fails(self):
        r = _validate(dc_replace(GOOD, atr_pct=0.09))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE5" in x for x in r.failure_reasons))

    def test_atr_too_high_fails(self):
        r = _validate(dc_replace(GOOD, atr_pct=6.01))
        self.assertFalse(r.passed)

    def test_atr_boundary_low_passes(self):
        r = _validate(dc_replace(GOOD, atr_pct=0.10))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGates6To9DeepSetupGap(unittest.TestCase):
    """Gates 6-9 must fail-closed when DeepSetup fields are absent (None)."""

    def test_gate6_missing_breakout(self):
        r = _validate(dc_replace(GOOD, breakout_level_price=None))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE6" in x for x in r.failure_reasons))

    def test_gate7_missing_retest_zone(self):
        r = _validate(dc_replace(GOOD, retest_zone_low=None, retest_zone_high=None))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE7" in x for x in r.failure_reasons))

    def test_gate7_zone_inverted_fails(self):
        r = _validate(dc_replace(GOOD, retest_zone_low=99.0, retest_zone_high=98.0))
        self.assertFalse(r.passed)

    def test_gate8_retest_not_confirmed(self):
        r = _validate(dc_replace(GOOD, retest_confirmed=False))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE8" in x for x in r.failure_reasons))

    def test_gate9_confirmation_candle_false(self):
        r = _validate(dc_replace(GOOD, confirmation_candle_closed=False))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE9" in x for x in r.failure_reasons))


class TestGate10Orientation(unittest.TestCase):
    def test_long_stop_above_entry_fails(self):
        # stop > entry → invalid LONG
        r = _validate(dc_replace(GOOD, direction="LONG", stop_loss=101.0, entry_trigger=99.8))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE10" in x for x in r.failure_reasons))

    def test_short_orientation_valid(self):
        # SHORT: tp1 <= entry < stop
        inp = dc_replace(
            GOOD,
            direction="SHORT",
            entry_trigger=99.8,
            take_profit_1=96.0,
            stop_loss=102.0,
        )
        r = _validate(inp)
        # May still fail other gates (GATE12 entry vs breakout orientation) but not GATE10
        gate10_failures = [x for x in r.failure_reasons if "GATE10" in x]
        self.assertEqual(gate10_failures, [])

    def test_short_orientation_violated_fails(self):
        inp = dc_replace(
            GOOD,
            direction="SHORT",
            entry_trigger=99.8,
            take_profit_1=101.0,  # tp1 > entry → invalid SHORT
            stop_loss=102.0,
        )
        r = _validate(inp)
        self.assertTrue(any("GATE10" in x for x in r.failure_reasons))


class TestGate11RewardRisk(unittest.TestCase):
    def test_rr_below_2_fails(self):
        r = _validate(dc_replace(GOOD, reward_risk=Decimal("1.99")))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE11" in x for x in r.failure_reasons))

    def test_rr_exactly_2_passes(self):
        r = _validate(dc_replace(GOOD, reward_risk=Decimal("2.0")))
        self.assertTrue(r.passed, r.failure_reasons)

    def test_rr_none_fails(self):
        r = _validate(dc_replace(GOOD, reward_risk=None))
        self.assertFalse(r.passed)


class TestGate12Chase(unittest.TestCase):
    def test_chase_exceeded_fails(self):
        # entry=99.8, breakout=100.0, dist=0.2; atr_15m=0.5 → limit=0.125 → 0.2 > 0.125
        r = _validate(dc_replace(GOOD, atr_15m_price=0.5))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE12" in x for x in r.failure_reasons))

    def test_within_chase_passes(self):
        # atr_15m=1.0 → limit=0.25; dist=0.2 → passes
        r = _validate(GOOD)  # GOOD already has atr_15m_price=1.0
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate13Funding(unittest.TestCase):
    def test_funding_above_threshold_fails(self):
        r = _validate(dc_replace(GOOD, funding_rate=0.0015))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE13" in x for x in r.failure_reasons))

    def test_funding_below_threshold_passes(self):
        r = _validate(dc_replace(GOOD, funding_rate=0.0014))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate14RelativeVolume(unittest.TestCase):
    def test_rvol_below_threshold_fails(self):
        r = _validate(dc_replace(GOOD, relative_volume=1.49))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE14" in x for x in r.failure_reasons))

    def test_rvol_at_threshold_passes(self):
        r = _validate(dc_replace(GOOD, relative_volume=1.5))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate15Liquidation(unittest.TestCase):
    def test_stop_not_before_liquidation_fails(self):
        r = _validate(dc_replace(GOOD, stop_precedes_liquidation=False))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE15" in x for x in r.failure_reasons))


class TestGate16Leverage(unittest.TestCase):
    def test_leverage_11_fails(self):
        r = _validate(dc_replace(GOOD, suggested_leverage=11))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE16" in x for x in r.failure_reasons))

    def test_leverage_10_passes(self):
        r = _validate(dc_replace(GOOD, suggested_leverage=10))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate17Decision(unittest.TestCase):
    def test_skip_decision_fails(self):
        r = _validate(dc_replace(GOOD, risk_decision="SKIP"))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE17" in x for x in r.failure_reasons))

    def test_reduce_decision_passes(self):
        r = _validate(dc_replace(GOOD, risk_decision="REDUCE"))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate18QuoteVolume(unittest.TestCase):
    def test_low_volume_fails(self):
        r = _validate(dc_replace(GOOD, quote_volume_24h=19_999_999.0))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE18" in x for x in r.failure_reasons))

    def test_volume_at_threshold_passes(self):
        r = _validate(dc_replace(GOOD, quote_volume_24h=20_000_000.0))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate19ChangeCapBoundary(unittest.TestCase):
    def test_change_above_15_fails(self):
        r = _validate(dc_replace(GOOD, change_24h_pct=15.1))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE19" in x for x in r.failure_reasons))

    def test_change_below_neg15_fails(self):
        r = _validate(dc_replace(GOOD, change_24h_pct=-15.1))
        self.assertFalse(r.passed)

    def test_change_at_boundary_passes(self):
        r = _validate(dc_replace(GOOD, change_24h_pct=15.0))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate20Sentiment(unittest.TestCase):
    def test_negative_sentiment_fails(self):
        r = _validate(dc_replace(GOOD, sentiment_score=-0.01))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE20" in x for x in r.failure_reasons))

    def test_zero_sentiment_passes(self):
        r = _validate(dc_replace(GOOD, sentiment_score=0.0))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate21OpposingGap(unittest.TestCase):
    def test_gap_too_small_fails(self):
        # effective=85, opposing=76 → gap=9 < 10
        r = _validate(dc_replace(GOOD, opposing_score=76.0))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE21" in x for x in r.failure_reasons))

    def test_gap_exactly_10_passes(self):
        # effective=85, opposing=75 → gap=10
        r = _validate(dc_replace(GOOD, opposing_score=75.0))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate22FundingAvailable(unittest.TestCase):
    def test_funding_not_available_fails(self):
        r = _validate(dc_replace(GOOD, funding_available=False))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE22" in x for x in r.failure_reasons))


class TestGate23Cooldown(unittest.TestCase):
    def test_within_cooldown_fails(self):
        r = _validate(dc_replace(GOOD, within_cooldown=True))
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE23" in x for x in r.failure_reasons))

    def test_outside_cooldown_passes(self):
        r = _validate(dc_replace(GOOD, within_cooldown=False))
        self.assertTrue(r.passed, r.failure_reasons)


class TestGate24EnableFlag(unittest.TestCase):
    def test_disabled_flag_fails(self):
        orig = os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)
        try:
            os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "0"
            r = _validate(GOOD)
            self.assertFalse(r.passed)
            self.assertTrue(any("GATE24" in x for x in r.failure_reasons))
        finally:
            if orig is None:
                os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)
            else:
                os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = orig

    def test_missing_flag_fails(self):
        orig = os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)
        try:
            r = _validate(GOOD)
            self.assertFalse(r.passed)
            self.assertTrue(any("GATE24" in x for x in r.failure_reasons))
        finally:
            if orig is not None:
                os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = orig


class TestMultipleGateFailures(unittest.TestCase):
    def test_all_none_input_fails_with_multiple_reasons(self):
        r = _validate(ExecutableSetupInput())
        self.assertFalse(r.passed)
        self.assertGreater(len(r.failure_reasons), 10)

    def test_failure_reasons_are_strings(self):
        r = _validate(ExecutableSetupInput())
        for reason in r.failure_reasons:
            self.assertIsInstance(reason, str)


class TestResultStructure(unittest.TestCase):
    def test_alert_id_always_present_on_good_input(self):
        r = _validate(GOOD)
        self.assertTrue(r.alert_id.startswith("LB_"))

    def test_alert_id_empty_when_prices_missing(self):
        r = _validate(dc_replace(GOOD, entry_trigger=None))
        self.assertEqual(r.alert_id, "")

    def test_failure_reasons_is_tuple(self):
        r = _validate(GOOD)
        self.assertIsInstance(r.failure_reasons, tuple)


if __name__ == "__main__":
    unittest.main()
