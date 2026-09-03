"""
Tests for ladybug_retest_detector.detect_retest().

Covers:
  R1  Insufficient candles → no detection (breakout_level_price is None).
  R2  Unknown direction → no detection.
  R3  SHORT: breakout_level = max of lookback window.
  R4  LONG:  breakout_level = min of lookback window.
  R5  SHORT retest confirmed when price is inside zone.
  R6  SHORT retest NOT confirmed when price is below zone (price below support, no retest yet).
  R7  SHORT retest NOT confirmed when price is far above zone (missed the retest).
  R8  LONG retest confirmed when price is inside zone.
  R9  LONG retest NOT confirmed when price is above zone.
  R10 SHORT confirmation candle: bearish close → True.
  R11 SHORT confirmation candle: bullish close → False.
  R12 LONG confirmation candle: bullish close → True.
  R13 LONG confirmation candle: bearish close → False.
  R14 Zone width scales with atr_pct (wider ATR → wider zone).
  R15 Zone width capped at 1.5 % when atr_pct is very large.
  R16 reason == "detected" for a successful detection.
  R17 reason describes the failure when detection is not possible.
  R18 Invalid price (zero/None) in candle data is skipped gracefully.
  R19 Short with all-zero closes → no_detection.
  R20 Open price unavailable → confirmation_candle_closed is None.
"""

import unittest
from decimal import Decimal

from sovereign_mission_engine.ladybug_retest_detector import detect_retest, RetestDetection


def _candles(closes, opens=None, n_head_filler=0):
    """Build a synthetic candle list from closes (and optional opens)."""
    result = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c * 0.999
        result.append({"close": str(c), "open": str(o), "high": str(c), "low": str(o)})
    return result


def _make_candles(n=100, base=100.0):
    """Flat candles around base price."""
    return _candles([base] * n, [base] * n)


# ── Candle shape helpers ──────────────────────────────────────────────────────

def _short_retest_candles(
    early_high=105.0,
    current_price=104.5,
    n=100,
    bearish_last=True,
):
    """
    Simulate SHORT retest:
      - Candles 0..86: high value (early_high) — consolidation before breakdown.
      - Candles 87..91: drop (75.0) — the breakdown.
      - Candles 92..99: bounce back toward early_high for the retest.
    Last candle open/close set to reflect bearish or bullish.
    """
    clos = []
    opens = []
    for i in range(n):
        if i < n - 13:
            c = early_high
        elif i < n - 8:
            c = 75.0
        else:
            c = current_price
        clos.append(c)
        o = c * 1.001 if (i == n - 1 and bearish_last) else c * 0.999
        opens.append(o)
    return _candles(clos, opens)


def _long_retest_candles(
    early_low=95.0,
    current_price=95.5,
    n=100,
    bullish_last=True,
):
    """
    Simulate LONG retest:
      - Candles 0..86: low value (early_low) — consolidation.
      - Candles 87..91: rise (125.0) — the breakout.
      - Candles 92..99: pullback toward early_low.
    """
    clos = []
    opens = []
    for i in range(n):
        if i < n - 13:
            c = early_low
        elif i < n - 8:
            c = 125.0
        else:
            c = current_price
        clos.append(c)
        o = c * 0.999 if (i == n - 1 and bullish_last) else c * 1.001
        opens.append(o)
    return _candles(clos, opens)


class TestRetestDetector(unittest.TestCase):

    # ── R1: insufficient candles ──────────────────────────────────────────────
    def test_r1_insufficient_candles(self):
        c = _make_candles(n=10)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertIsNone(r.breakout_level_price)

    # ── R2: unknown direction ─────────────────────────────────────────────────
    def test_r2_unknown_direction(self):
        c = _make_candles(n=100)
        r = detect_retest(c, direction="SIDEWAYS", last_price=100.0, atr_pct=1.0)
        self.assertIsNone(r.breakout_level_price)

    # ── R3: SHORT breakout level = max of lookback ────────────────────────────
    def test_r3_short_breakout_level_is_max(self):
        # Candles flat at 100, one spike to 120 in the middle of lookback
        clos = [100.0] * 100
        clos[40] = 120.0  # spike inside lookback window [3:-8]
        c = _candles(clos)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertAlmostEqual(r.breakout_level_price, 120.0)

    # ── R4: LONG breakout level = min of lookback ─────────────────────────────
    def test_r4_long_breakout_level_is_min(self):
        clos = [100.0] * 100
        clos[40] = 80.0  # dip inside lookback
        c = _candles(clos)
        r = detect_retest(c, direction="LONG", last_price=100.0, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertAlmostEqual(r.breakout_level_price, 80.0)

    # ── R5: SHORT retest confirmed (price inside zone) ────────────────────────
    def test_r5_short_retest_confirmed(self):
        c = _short_retest_candles(early_high=105.0, current_price=104.8)
        r = detect_retest(c, direction="SHORT", last_price=104.8, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertTrue(r.retest_confirmed, f"zone={r.retest_zone_low:.2f}..{r.retest_zone_high:.2f}, price=104.8")

    # ── R6: SHORT retest NOT confirmed (price below zone — breakdown in progress)
    def test_r6_short_retest_not_confirmed_below(self):
        c = _short_retest_candles(early_high=105.0, current_price=75.0)
        r = detect_retest(c, direction="SHORT", last_price=75.0, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertFalse(r.retest_confirmed)

    # ── R7: SHORT retest NOT confirmed (price far above zone) ─────────────────
    def test_r7_short_retest_not_confirmed_above(self):
        c = _short_retest_candles(early_high=105.0, current_price=115.0)
        r = detect_retest(c, direction="SHORT", last_price=115.0, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertFalse(r.retest_confirmed)

    # ── R8: LONG retest confirmed ─────────────────────────────────────────────
    def test_r8_long_retest_confirmed(self):
        c = _long_retest_candles(early_low=95.0, current_price=95.3)
        r = detect_retest(c, direction="LONG", last_price=95.3, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertTrue(r.retest_confirmed, f"zone={r.retest_zone_low:.2f}..{r.retest_zone_high:.2f}, price=95.3")

    # ── R9: LONG retest NOT confirmed (price above zone) ─────────────────────
    def test_r9_long_retest_not_confirmed_above(self):
        c = _long_retest_candles(early_low=95.0, current_price=125.0)
        r = detect_retest(c, direction="LONG", last_price=125.0, atr_pct=1.0)
        self.assertIsNotNone(r.breakout_level_price)
        self.assertFalse(r.retest_confirmed)

    # ── R10: SHORT confirmation candle bearish ────────────────────────────────
    def test_r10_short_confirmation_bearish(self):
        c = _short_retest_candles(early_high=105.0, current_price=104.8, bearish_last=True)
        r = detect_retest(c, direction="SHORT", last_price=104.8, atr_pct=1.0)
        self.assertTrue(r.confirmation_candle_closed)

    # ── R11: SHORT confirmation candle bullish → False ────────────────────────
    def test_r11_short_confirmation_bullish_is_false(self):
        c = _short_retest_candles(early_high=105.0, current_price=104.8, bearish_last=False)
        r = detect_retest(c, direction="SHORT", last_price=104.8, atr_pct=1.0)
        self.assertFalse(r.confirmation_candle_closed)

    # ── R12: LONG confirmation candle bullish ─────────────────────────────────
    def test_r12_long_confirmation_bullish(self):
        c = _long_retest_candles(early_low=95.0, current_price=95.3, bullish_last=True)
        r = detect_retest(c, direction="LONG", last_price=95.3, atr_pct=1.0)
        self.assertTrue(r.confirmation_candle_closed)

    # ── R13: LONG confirmation candle bearish → False ─────────────────────────
    def test_r13_long_confirmation_bearish_is_false(self):
        c = _long_retest_candles(early_low=95.0, current_price=95.3, bullish_last=False)
        r = detect_retest(c, direction="LONG", last_price=95.3, atr_pct=1.0)
        self.assertFalse(r.confirmation_candle_closed)

    # ── R14: Zone widens with larger ATR ─────────────────────────────────────
    def test_r14_zone_scales_with_atr(self):
        clos = [100.0] * 100
        c = _candles(clos)
        r_narrow = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=0.5)
        r_wide = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=3.0)
        self.assertIsNotNone(r_narrow.breakout_level_price)
        self.assertIsNotNone(r_wide.breakout_level_price)
        narrow_width = r_narrow.retest_zone_high - r_narrow.retest_zone_low
        wide_width = r_wide.retest_zone_high - r_wide.retest_zone_low
        self.assertGreater(wide_width, narrow_width)

    # ── R15: Zone width capped at 1.5 % ──────────────────────────────────────
    def test_r15_zone_width_capped(self):
        clos = [100.0] * 100
        c = _candles(clos)
        # atr_pct=10 → 0.4×10=4.0 > 1.5, so cap applies
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=10.0)
        self.assertIsNotNone(r.breakout_level_price)
        width_pct = (r.retest_zone_high - r.retest_zone_low) / r.breakout_level_price * 100
        self.assertAlmostEqual(width_pct, 3.0, places=5)  # 2×1.5 % = 3 % total

    # ── R16: reason == "detected" on success ─────────────────────────────────
    def test_r16_reason_detected_on_success(self):
        clos = [100.0] * 100
        c = _candles(clos)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertEqual(r.reason, "detected")

    # ── R17: reason describes failure ─────────────────────────────────────────
    def test_r17_reason_on_insufficient(self):
        c = _make_candles(n=5)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertNotEqual(r.reason, "detected")
        self.assertIsNotNone(r.reason)

    # ── R18: zero-price candles are skipped ───────────────────────────────────
    def test_r18_zero_prices_skipped(self):
        # Mix valid and zero-price candles
        clos = [100.0] * 90 + [0.0] * 5 + [100.0] * 5
        c = _candles(clos)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        # Should still work because we have enough valid closes
        self.assertIsNotNone(r.breakout_level_price)

    # ── R19: All-zero closes → no detection ──────────────────────────────────
    def test_r19_all_zero_closes_no_detection(self):
        clos = [0.0] * 100
        c = _candles(clos)
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertIsNone(r.breakout_level_price)

    # ── R20: Missing open → confirmation_candle_closed is None ───────────────
    def test_r20_missing_open_none_confirmation(self):
        clos = [100.0] * 100
        # Candles without "open" key
        c = [{"close": str(v)} for v in clos]
        r = detect_retest(c, direction="SHORT", last_price=100.0, atr_pct=1.0)
        self.assertIsNone(r.confirmation_candle_closed)


if __name__ == "__main__":
    unittest.main()
