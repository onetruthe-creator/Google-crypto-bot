"""
Shadow integration test for the Ladybug executable-alert pipeline.

Exercises the validator → formatter → delivery chain end-to-end without
any network calls.  The relay_alert function and state I/O are monkey-patched.

9 required conditions per spec:
 S1  A CONFIRMED_ANALYSIS setup that fails Gate 6 (no breakout level) never
     reaches the formatter.
 S2  A setup passing all 24 gates produces a non-empty formatted message.
 S3  The formatted message contains the exact literal "CONFIRMED_SETUP — EXECUTABLE".
 S4  The formatted message contains "AUTHORIZATION: NONE".
 S5  The delivery layer calls relay_alert exactly once for a passing setup.
 S6  A second call with the same alert_id within cooldown does NOT call relay_alert again.
 S7  When LADYBUG_EXECUTABLE_ALERTS_ENABLED=0, relay_alert is never called.
 S8  A passing setup is recorded in the dedup store after delivery.
 S9  A relay_alert exception returns a failed result (delivery failure propagated).
"""

import os
import time
import unittest
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "1"

from sovereign_mission_engine.lb_executable_validator import (
    ExecutableSetupInput,
    compute_alert_id,
)
from sovereign_mission_engine.lb_executable_formatter import format_executable_alert

_TS = datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

SHADOW_GOOD = ExecutableSetupInput(
    admission_status="CONFIRMED_ANALYSIS",
    admission_admitted=True,
    effective_score=88.0,
    direction="LONG",
    move_1h_pct=1.5,
    atr_pct=1.2,
    breakout_level_price=50000.0,
    retest_zone_low=49500.0,
    retest_zone_high=49900.0,
    retest_confirmed=True,
    confirmation_candle_closed=True,
    entry_trigger=50050.0,       # dist from breakout=50.0; atr_15m_price=400 → limit=100
    take_profit_1=51500.0,
    stop_loss=49000.0,
    reward_risk=Decimal("2.35"),
    atr_15m_price=400.0,
    funding_rate=0.0001,
    relative_volume=2.5,
    stop_precedes_liquidation=True,
    suggested_leverage=5,
    risk_decision="TRADE",
    quote_volume_24h=80_000_000.0,
    change_24h_pct=2.0,
    sentiment_score=0.6,
    opposing_score=70.0,
    funding_available=True,
    within_cooldown=False,
    symbol="BTCUSDT",
    scan_timestamp=_TS,
)


def _make_delivery_module():
    """Import delivery module fresh with runtime stubs."""
    import importlib
    import sovereign_mission_engine.lb_executable_delivery as mod
    importlib.reload(mod)
    return mod


class TestShadowS1NoBreakoutNeverFormats(unittest.TestCase):
    """S1: missing breakout_level_price (Gate 6 fail) never reaches formatter."""

    def test_s1(self):
        from sovereign_mission_engine.lb_executable_validator import validate_executable_setup
        inp = dc_replace(SHADOW_GOOD, breakout_level_price=None)
        r = validate_executable_setup(inp)
        self.assertFalse(r.passed)
        self.assertTrue(any("GATE6" in x for x in r.failure_reasons))
        # formatter must not be called
        with self.assertRaises(ValueError):
            format_executable_alert(inp, r)


class TestShadowS2S3S4FormattedMessage(unittest.TestCase):
    """S2, S3, S4: passing setup produces correct formatted message."""

    def setUp(self):
        from sovereign_mission_engine.lb_executable_validator import validate_executable_setup
        r = validate_executable_setup(SHADOW_GOOD)
        self.assertTrue(r.passed, r.failure_reasons)
        self.result = r
        self.message = format_executable_alert(SHADOW_GOOD, r)

    def test_s2_message_non_empty(self):
        self.assertGreater(len(self.message), 50)

    def test_s3_contains_confirmed_setup_executable(self):
        self.assertIn("CONFIRMED_SETUP — EXECUTABLE", self.message)

    def test_s4_contains_authorization_none(self):
        self.assertIn("AUTHORIZATION: NONE", self.message)


class TestShadowS5RelayCalledOnce(unittest.TestCase):
    """S5: relay_alert called exactly once for a passing setup."""

    def test_s5(self):
        relay_mock = MagicMock()
        empty_state = {"sent": {}}

        with patch.dict(os.environ, {"LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}):
            with patch(
                "sovereign_mission_engine.lb_executable_delivery.relay_alert",
                relay_mock,
            ):
                with patch(
                    "sovereign_mission_engine.lb_executable_delivery._load_state",
                    return_value=empty_state,
                ):
                    with patch(
                        "sovereign_mission_engine.lb_executable_delivery._save_state"
                    ):
                        from sovereign_mission_engine.lb_executable_delivery import (
                            try_deliver_executable,
                        )
                        r = try_deliver_executable(SHADOW_GOOD)

        self.assertTrue(r.passed, r.failure_reasons)
        relay_mock.assert_called_once()


class TestShadowS6DedupPreventsSecondRelay(unittest.TestCase):
    """S6: second call with same alert_id within cooldown does not relay again."""

    def test_s6(self):
        aid = compute_alert_id(
            symbol=SHADOW_GOOD.symbol,
            direction=SHADOW_GOOD.direction,
            entry_trigger=SHADOW_GOOD.entry_trigger,
            stop_loss=SHADOW_GOOD.stop_loss,
            take_profit_1=SHADOW_GOOD.take_profit_1,
            scan_timestamp=SHADOW_GOOD.scan_timestamp,
        )
        # Simulate state where alert was already sent 1 second ago
        now = time.time()
        existing_state = {"sent": {aid: {"ts": now - 1, "symbol": "BTCUSDT"}}}

        relay_mock = MagicMock()
        with patch.dict(os.environ, {"LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}):
            with patch(
                "sovereign_mission_engine.lb_executable_delivery.relay_alert",
                relay_mock,
            ):
                with patch(
                    "sovereign_mission_engine.lb_executable_delivery._load_state",
                    return_value=existing_state,
                ):
                    with patch(
                        "sovereign_mission_engine.lb_executable_delivery._save_state"
                    ):
                        from sovereign_mission_engine.lb_executable_delivery import (
                            try_deliver_executable,
                        )
                        r = try_deliver_executable(SHADOW_GOOD)

        self.assertFalse(r.passed)
        self.assertTrue(any("GATE23" in x for x in r.failure_reasons))
        relay_mock.assert_not_called()


class TestShadowS7DisabledFlagNoRelay(unittest.TestCase):
    """S7: LADYBUG_EXECUTABLE_ALERTS_ENABLED=0 → relay_alert never called."""

    def test_s7(self):
        relay_mock = MagicMock()
        with patch.dict(os.environ, {"LADYBUG_EXECUTABLE_ALERTS_ENABLED": "0"}):
            with patch(
                "sovereign_mission_engine.lb_executable_delivery.relay_alert",
                relay_mock,
            ):
                with patch(
                    "sovereign_mission_engine.lb_executable_delivery._load_state",
                    return_value={"sent": {}},
                ):
                    with patch(
                        "sovereign_mission_engine.lb_executable_delivery._save_state"
                    ):
                        from sovereign_mission_engine.lb_executable_delivery import (
                            try_deliver_executable,
                        )
                        r = try_deliver_executable(SHADOW_GOOD)

        self.assertFalse(r.passed)
        relay_mock.assert_not_called()


class TestShadowS8RecordedAfterDelivery(unittest.TestCase):
    """S8: passing alert is recorded in dedup store after delivery."""

    def test_s8(self):
        saved_state = {}

        def fake_save(state):
            saved_state.update(state)

        with patch.dict(os.environ, {"LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}):
            with patch(
                "sovereign_mission_engine.lb_executable_delivery.relay_alert",
            ):
                with patch(
                    "sovereign_mission_engine.lb_executable_delivery._load_state",
                    return_value={"sent": {}},
                ):
                    with patch(
                        "sovereign_mission_engine.lb_executable_delivery._save_state",
                        side_effect=fake_save,
                    ):
                        from sovereign_mission_engine.lb_executable_delivery import (
                            try_deliver_executable,
                        )
                        r = try_deliver_executable(SHADOW_GOOD)

        self.assertTrue(r.passed, r.failure_reasons)
        self.assertIn(r.alert_id, saved_state.get("sent", {}))


class TestShadowS9RelayExceptionPropagated(unittest.TestCase):
    """S9: relay_alert raising an exception returns a failed result."""

    def test_s9(self):
        def boom(*args, **kwargs):
            raise RuntimeError("network down")

        with patch.dict(os.environ, {"LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}):
            with patch(
                "sovereign_mission_engine.lb_executable_delivery.relay_alert",
                side_effect=boom,
            ):
                with patch(
                    "sovereign_mission_engine.lb_executable_delivery._load_state",
                    return_value={"sent": {}},
                ):
                    with patch(
                        "sovereign_mission_engine.lb_executable_delivery._save_state"
                    ):
                        from sovereign_mission_engine.lb_executable_delivery import (
                            try_deliver_executable,
                        )
                        r = try_deliver_executable(SHADOW_GOOD)

        self.assertFalse(r.passed)
        self.assertTrue(any("RELAY_ERROR" in x for x in r.failure_reasons))


if __name__ == "__main__":
    unittest.main()
