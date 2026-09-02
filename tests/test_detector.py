import pytest
from ladybug.detector import (
    Candle, parse_candle, find_resistance_levels,
    avg_volume, calculate_rsi,
    detect_breakout, detect_retest, detect_rejection,
)


def _c(o, h, l, c, v, ts=0) -> Candle:
    return Candle(ts, float(o), float(h), float(l), float(c), float(v))


def test_parse_candle_list():
    raw = [1000, 100, 110, 90, 105, 500]
    c = parse_candle(raw)
    assert c.timestamp == 1000
    assert c.open == 100
    assert c.volume == 500


def test_parse_candle_dict():
    raw = {"t": 2000, "o": "50", "h": "55", "l": "45", "c": "52", "v": "300"}
    c = parse_candle(raw)
    assert c.timestamp == 2000
    assert c.close == 52.0
    assert c.volume == 300.0


def test_find_resistance_levels_basic():
    candles = [_c(100, h, 90, 100, 100) for h in [100, 105, 120, 105, 100, 95, 100, 105, 100, 95, 100]]
    levels = find_resistance_levels(candles, swing_lookback=2)
    assert any(abs(l - 120) < 0.01 for l in levels)


def test_find_resistance_levels_empty():
    assert find_resistance_levels([], 5) == []


def test_avg_volume_basic():
    candles = [_c(0, 0, 0, 0, v=float(v)) for v in range(1, 11)]
    result = avg_volume(candles, n=5)
    assert result == pytest.approx(8.0)  # last 5: 6,7,8,9,10 → mean=8


def test_avg_volume_all():
    candles = [_c(0, 0, 0, 0, v=10.0) for _ in range(5)]
    assert avg_volume(candles, n=20) == pytest.approx(10.0)


def test_calculate_rsi_not_enough():
    candles = [_c(0, 0, 0, 0, 0) for _ in range(5)]
    assert calculate_rsi(candles, 14) == pytest.approx(50.0)


def test_calculate_rsi_all_gains():
    candles = [_c(0, 0, 0, 0, float(i), 0) for i in range(1, 25)]
    rsi = calculate_rsi(candles, 14)
    assert rsi == pytest.approx(100.0)


def test_detect_breakout_true():
    level = 100.0
    candles = [_c(95, 99, 93, 98, 100)] * 20 + [_c(98, 101, 97, 101, 250)]
    assert detect_breakout(candles, level, vol_mult=2.0)


def test_detect_breakout_false_low_volume():
    level = 100.0
    candles = [_c(95, 99, 93, 98, 100)] * 20 + [_c(98, 101, 97, 101, 100)]
    assert not detect_breakout(candles, level, vol_mult=2.0)


def test_detect_retest_true():
    level = 100.0
    candles = [_c(102, 104, 99.4, 102, 50)]
    assert detect_retest(candles, level, tolerance_pct=0.5)


def test_detect_retest_false():
    level = 100.0
    candles = [_c(110, 112, 108, 110, 50)]
    assert not detect_retest(candles, level, tolerance_pct=0.5)


def test_detect_rejection_true():
    level = 100.0
    candles = [_c(101, 102, 99.5, 102.5, 50)]
    assert detect_rejection(candles, level, min_move_pct=0.3)


def test_detect_rejection_false_bearish():
    level = 100.0
    candles = [_c(103, 104, 99.5, 100.5, 50)]
    assert not detect_rejection(candles, level, min_move_pct=0.3)
