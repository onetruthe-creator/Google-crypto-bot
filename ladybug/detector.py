from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_candle(raw: dict | list) -> Candle:
    if isinstance(raw, (list, tuple)):
        return Candle(int(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]), float(raw[5]))
    def _f(keys: list[str]) -> float:
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return float(v)
        return 0.0
    def _i(keys: list[str]) -> int:
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return int(v)
        return 0
    return Candle(
        timestamp=_i(["t", "ts", "time", "openTime", "timestamp"]),
        open=_f(["o", "open"]),
        high=_f(["h", "high"]),
        low=_f(["l", "low"]),
        close=_f(["c", "close"]),
        volume=_f(["v", "vol", "volume"]),
    )


def find_resistance_levels(candles: Sequence[Candle], swing_lookback: int = 5) -> list[float]:
    levels: list[float] = []
    n = len(candles)
    for i in range(swing_lookback, n - swing_lookback):
        c = candles[i]
        window = [candles[j] for j in range(i - swing_lookback, i + swing_lookback + 1) if j != i]
        if all(c.high >= w.high for w in window):
            levels.append(c.high)
    return levels


def avg_volume(candles: Sequence[Candle], n: int = 20) -> float:
    recent = list(candles[-n:]) if len(candles) >= n else list(candles)
    if not recent:
        return 0.0
    return sum(c.volume for c in recent) / len(recent)


def calculate_rsi(candles: Sequence[Candle], period: int = 14) -> float:
    closes = [c.close for c in candles]
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def detect_breakout(
    candles: Sequence[Candle],
    level: float,
    vol_mult: float = 1.5,
    lookback: int = 20,
) -> bool:
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    av = avg_volume(candles[:-1], lookback)
    return prev.close < level and curr.close > level and curr.volume >= av * vol_mult


def detect_retest(
    candles: Sequence[Candle],
    level: float,
    tolerance_pct: float = 0.5,
) -> bool:
    if not candles:
        return False
    curr = candles[-1]
    tol = level * tolerance_pct / 100.0
    return curr.low <= level + tol and curr.close > level - tol


def detect_rejection(
    candles: Sequence[Candle],
    level: float,
    min_move_pct: float = 0.3,
) -> bool:
    if not candles:
        return False
    curr = candles[-1]
    min_move = level * min_move_pct / 100.0
    return curr.close > level and (curr.close - curr.low) >= min_move and curr.close > curr.open
