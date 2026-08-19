#!/usr/bin/env python3
"""
Simple, dependency-free backtester for a moving-average crossover strategy.

This exists so you can see the *mechanics* of backtesting: iterating bar by
bar, generating entry/exit signals from an objective rule, sizing positions
by risk %, and measuring the real results (win rate, average R, drawdown).
Modify the signal logic (see `generate_signal`) to test your own strategy
rules from `learn/02_strategy_basics.md`.

Strategy implemented by default: EMA(fast) crosses above EMA(slow) => go long.
EMA(fast) crosses below EMA(slow) => close long / go short (if --allow-short).
Stop-loss = ATR(period) * atr-mult below entry (long) / above entry (short).
Position size = risk_pct% of current equity / stop distance (see
tools/position_sizing.py for the same formula standalone).

Usage:
    python3 backtest.py --data ../sample_data/sample_ohlcv.csv

Input CSV format (header required): Date,Open,High,Low,Close,Volume
"""
from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass, field


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    direction: str
    entry_date: str
    entry_price: float
    stop_price: float
    size: float
    dollar_risk: float
    exit_date: str = ""
    exit_price: float = 0.0
    pnl: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ""


def load_bars(path: str) -> list[Bar]:
    bars = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")
        for row in reader:
            bars.append(Bar(
                date=row["Date"],
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            ))
    return bars


def ema_series(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average; None until enough data exists."""
    k = 2 / (period + 1)
    out: list[float | None] = [None] * len(values)
    ema = None
    for i, v in enumerate(values):
        if i < period - 1:
            continue
        if ema is None:
            ema = sum(values[i - period + 1: i + 1]) / period  # seed with SMA
        else:
            ema = v * k + ema * (1 - k)
        out[i] = ema
    return out


def atr_series(bars: list[Bar], period: int) -> list[float | None]:
    trs: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            trs.append(bar.high - bar.low)
            continue
        prev_close = bars[i - 1].close
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )
        trs.append(tr)

    out: list[float | None] = [None] * len(bars)
    atr = None
    for i, tr in enumerate(trs):
        if i < period - 1:
            continue
        if atr is None:
            atr = sum(trs[i - period + 1: i + 1]) / period
        else:
            atr = (atr * (period - 1) + tr) / period
        out[i] = atr
    return out


def run_backtest(
    bars: list[Bar],
    fast_period: int,
    slow_period: int,
    atr_period: int,
    atr_mult: float,
    risk_pct: float,
    initial_balance: float,
    allow_short: bool,
) -> tuple[list[Trade], list[float]]:
    closes = [b.close for b in bars]
    fast = ema_series(closes, fast_period)
    slow = ema_series(closes, slow_period)
    atr = atr_series(bars, atr_period)

    equity = initial_balance
    equity_curve = [equity]
    trades: list[Trade] = []
    position: Trade | None = None
    prev_fast_above: bool | None = None

    for i, bar in enumerate(bars):
        if fast[i] is None or slow[i] is None or atr[i] is None:
            equity_curve.append(equity)
            continue

        fast_above = fast[i] > slow[i]

        # Manage open position: check stop first (using this bar's low/high)
        if position is not None:
            if position.direction == "long" and bar.low <= position.stop_price:
                _close_trade(position, bar.date, position.stop_price, "stop")
                equity += position.pnl
                trades.append(position)
                position = None
            elif position.direction == "short" and bar.high >= position.stop_price:
                _close_trade(position, bar.date, position.stop_price, "stop")
                equity += position.pnl
                trades.append(position)
                position = None

        # Signal-based exit/flip on crossover change
        if prev_fast_above is not None and fast_above != prev_fast_above and position is not None:
            _close_trade(position, bar.date, bar.close, "signal_flip")
            equity += position.pnl
            trades.append(position)
            position = None

        # New entry if flat
        if position is None and prev_fast_above is not None and fast_above != prev_fast_above:
            stop_distance = atr[i] * atr_mult
            if stop_distance > 0:
                dollar_risk = equity * (risk_pct / 100)
                size = dollar_risk / stop_distance
                if fast_above:
                    stop_price = bar.close - stop_distance
                    position = Trade(
                        direction="long", entry_date=bar.date, entry_price=bar.close,
                        stop_price=stop_price, size=size, dollar_risk=dollar_risk,
                    )
                elif allow_short:
                    stop_price = bar.close + stop_distance
                    position = Trade(
                        direction="short", entry_date=bar.date, entry_price=bar.close,
                        stop_price=stop_price, size=size, dollar_risk=dollar_risk,
                    )

        prev_fast_above = fast_above
        equity_curve.append(equity)

    # Close any still-open position at the last bar's close (mark-to-market)
    if position is not None:
        _close_trade(position, bars[-1].date, bars[-1].close, "end_of_data")
        equity += position.pnl
        trades.append(position)
        equity_curve[-1] = equity

    return trades, equity_curve


def _close_trade(trade: Trade, exit_date: str, exit_price: float, reason: str) -> None:
    trade.exit_date = exit_date
    trade.exit_price = exit_price
    trade.exit_reason = reason
    if trade.direction == "long":
        trade.pnl = (exit_price - trade.entry_price) * trade.size
    else:
        trade.pnl = (trade.entry_price - exit_price) * trade.size
    trade.r_multiple = trade.pnl / trade.dollar_risk if trade.dollar_risk else 0.0


def max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    worst = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0
        worst = max(worst, dd)
    return worst * 100


def summarize(trades: list[Trade], equity_curve: list[float], initial_balance: float) -> None:
    if not trades:
        print("No trades were generated -- try a longer dataset or different MA periods.")
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100
    avg_r = statistics.mean(t.r_multiple for t in trades)
    total_pnl = sum(t.pnl for t in trades)
    final_equity = equity_curve[-1]
    total_return_pct = (final_equity / initial_balance - 1) * 100
    dd = max_drawdown(equity_curve)

    print("\n=== Backtest Summary ===")
    print(f"Total trades:        {len(trades)}")
    print(f"Win rate:            {win_rate:.1f}%  ({len(wins)} wins / {len(losses)} losses)")
    print(f"Average R-multiple:  {avg_r:.2f}R")
    print(f"Total PnL:           ${total_pnl:,.2f}")
    print(f"Starting balance:    ${initial_balance:,.2f}")
    print(f"Ending balance:      ${final_equity:,.2f}")
    print(f"Total return:        {total_return_pct:.1f}%")
    print(f"Max drawdown:        {dd:.1f}%")
    print()
    print("Reminder: this is historical simulation on the specific dataset given.")
    print("A profitable backtest is a *prerequisite* for live trading, not a guarantee --")
    print("always forward-test on demo before risking real capital (see study_plan.md).")


def write_trades_csv(trades: list[Trade], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "direction", "entry_date", "entry_price", "stop_price", "size",
            "dollar_risk", "exit_date", "exit_price", "pnl", "r_multiple", "exit_reason",
        ])
        for t in trades:
            writer.writerow([
                t.direction, t.entry_date, round(t.entry_price, 4), round(t.stop_price, 4),
                round(t.size, 4), round(t.dollar_risk, 2), t.exit_date, round(t.exit_price, 4),
                round(t.pnl, 2), round(t.r_multiple, 2), t.exit_reason,
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Dependency-free MA-crossover backtester")
    parser.add_argument("--data", required=True, help="Path to OHLCV CSV file")
    parser.add_argument("--fast", type=int, default=20, help="Fast EMA period (default 20)")
    parser.add_argument("--slow", type=int, default=50, help="Slow EMA period (default 50)")
    parser.add_argument("--atr-period", type=int, default=14, help="ATR period (default 14)")
    parser.add_argument("--atr-mult", type=float, default=2.0, help="Stop = ATR * this (default 2.0)")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="Risk %% of equity per trade (default 1.0)")
    parser.add_argument("--initial-balance", type=float, default=2000.0)
    parser.add_argument("--allow-short", action="store_true", help="Allow short trades on bearish crossover")
    parser.add_argument("--out-trades", default=None, help="Optional path to write trades CSV")
    args = parser.parse_args()

    bars = load_bars(args.data)
    if len(bars) < args.slow + args.atr_period:
        print("Warning: dataset may be too short for the chosen MA/ATR periods.")

    trades, equity_curve = run_backtest(
        bars=bars,
        fast_period=args.fast,
        slow_period=args.slow,
        atr_period=args.atr_period,
        atr_mult=args.atr_mult,
        risk_pct=args.risk_pct,
        initial_balance=args.initial_balance,
        allow_short=args.allow_short,
    )

    summarize(trades, equity_curve, args.initial_balance)

    if args.out_trades:
        write_trades_csv(trades, args.out_trades)
        print(f"\nWrote {len(trades)} trades to {args.out_trades}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
