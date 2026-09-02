import pytest
from ladybug.detector import Candle
from ladybug.gates import check_gates, setup_still_valid
from ladybug.state import Phase, SymbolState


def _c(close=100.0, volume=1000.0, low=None, high=None, open_=None) -> Candle:
    l = low if low is not None else close * 0.99
    h = high if high is not None else close * 1.01
    o = open_ if open_ is not None else close * 0.995
    return Candle(0, o, h, l, close, volume)


def _make_candles(n=30, close=105.0, volume=10_000.0) -> list[Candle]:
    # alternating up/down so RSI stays mid-range, last candle at `close`
    candles = []
    for i in range(n - 1):
        c = close + (1.0 if i % 2 == 0 else -1.0)
        candles.append(_c(close=c, volume=volume))
    candles.append(_c(close=close, volume=volume))
    return candles


def _rejection_state(level=100.0) -> SymbolState:
    s = SymbolState(symbol="BTCUSDT")
    s.phase = Phase.REJECTION
    s.level = level
    return s


def test_gates_pass_all():
    candles = _make_candles(30, close=105.0, volume=10_000.0)
    state = _rejection_state(100.0)
    result = check_gates(candles, state, rsi_max=80.0, min_volume_usdt=100_000.0)
    assert result.passed


def test_gates_fail_price_below_level():
    # last candle close explicitly below level 100
    candles = _make_candles(30, close=105.0, volume=10_000.0)
    candles[-1] = _c(close=98.0, volume=10_000.0)
    state = _rejection_state(100.0)
    result = check_gates(candles, state, rsi_max=80.0, min_volume_usdt=100_000.0)
    assert not result.passed
    assert any("price" in r for r in result.reasons)


def test_gates_fail_wrong_phase():
    candles = _make_candles(30)
    state = SymbolState(symbol="X")
    state.phase = Phase.NONE
    result = check_gates(candles, state)
    assert not result.passed


def test_setup_valid():
    candles = _make_candles(30, close=102.0)
    state = _rejection_state(100.0)
    assert setup_still_valid(candles, state)


def test_setup_invalid_below_level():
    # last candle close well below level 100 (invalidation threshold is level * 0.995 = 99.5)
    candles = _make_candles(30, close=105.0)
    candles[-1] = _c(close=98.0)  # 2% below level → invalid
    state = _rejection_state(100.0)
    assert not setup_still_valid(candles, state)


def test_setup_invalid_confirmed_phase():
    candles = _make_candles(30, close=105.0)
    state = _rejection_state(100.0)
    state.phase = Phase.CONFIRMED
    assert not setup_still_valid(candles, state)
