#!/usr/bin/env python3
"""
Position sizing / risk calculator.

Computes how many shares/units/contracts to trade so that a stop-loss hit
costs exactly your chosen % risk of account balance -- never more.

Usage (interactive):
    python3 position_sizing.py

Usage (non-interactive, all args on command line):
    python3 position_sizing.py --balance 2000 --risk-pct 1 \
        --entry 50 --stop 48 --direction long

Usage (as a library):
    from position_sizing import position_size
    result = position_size(balance=2000, risk_pct=1, entry=50, stop=48)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass


@dataclass
class PositionSizeResult:
    dollar_risk: float
    stop_distance: float
    size: float
    position_value: float
    position_pct_of_account: float
    reward_1r: float
    reward_2r: float
    reward_3r: float
    warning: str | None


def position_size(
    balance: float,
    risk_pct: float,
    entry: float,
    stop: float,
    direction: str = "long",
) -> PositionSizeResult:
    if balance <= 0:
        raise ValueError("balance must be > 0")
    if not (0 < risk_pct <= 100):
        raise ValueError("risk_pct must be between 0 and 100")
    if entry <= 0 or stop <= 0:
        raise ValueError("entry and stop must be > 0")
    if entry == stop:
        raise ValueError("entry and stop cannot be equal (zero stop distance)")

    direction = direction.lower()
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if direction == "long" and stop >= entry:
        raise ValueError("for a long trade, stop must be below entry")
    if direction == "short" and stop <= entry:
        raise ValueError("for a short trade, stop must be above entry")

    dollar_risk = balance * (risk_pct / 100)
    stop_distance = abs(entry - stop)
    size = dollar_risk / stop_distance
    position_value = size * entry
    position_pct_of_account = (position_value / balance) * 100

    if direction == "long":
        r1 = entry + stop_distance
        r2 = entry + 2 * stop_distance
        r3 = entry + 3 * stop_distance
    else:
        r1 = entry - stop_distance
        r2 = entry - 2 * stop_distance
        r3 = entry - 3 * stop_distance

    warning = None
    if position_pct_of_account > 100:
        warning = (
            f"Position value (${position_value:,.2f}) exceeds account balance "
            f"(${balance:,.2f}). Your stop is very tight relative to your risk %; "
            "check for leverage requirements or widen the stop."
        )
    elif position_pct_of_account > 50:
        warning = (
            f"Position uses {position_pct_of_account:.1f}% of account value. "
            "That's a large concentration even though the *risk* is capped correctly -- "
            "make sure you're comfortable with that much capital tied up in one position."
        )
    if risk_pct > 2:
        extra = (
            f"Risk % of {risk_pct}% is above the recommended 1-2% max per trade for "
            "beginners. Consider lowering it."
        )
        warning = f"{warning} {extra}" if warning else extra

    return PositionSizeResult(
        dollar_risk=dollar_risk,
        stop_distance=stop_distance,
        size=size,
        position_value=position_value,
        position_pct_of_account=position_pct_of_account,
        reward_1r=r1,
        reward_2r=r2,
        reward_3r=r3,
        warning=warning,
    )


def print_result(balance: float, risk_pct: float, entry: float, stop: float,
                  direction: str, result: PositionSizeResult) -> None:
    print("\n--- Position Sizing Result ---")
    print(f"Account balance:        ${balance:,.2f}")
    print(f"Risk %:                 {risk_pct}%")
    print(f"Direction:              {direction}")
    print(f"Entry price:            ${entry:,.4f}")
    print(f"Stop price:             ${stop:,.4f}")
    print(f"Stop distance:          ${result.stop_distance:,.4f}")
    print("-" * 32)
    print(f"Dollar risk (1R):       ${result.dollar_risk:,.2f}")
    print(f"Position size:          {result.size:,.4f} units/shares/contracts")
    print(f"Position value:         ${result.position_value:,.2f}")
    print(f"% of account deployed:  {result.position_pct_of_account:.2f}%")
    print("-" * 32)
    print(f"Target @ 1R:            ${result.reward_1r:,.4f}")
    print(f"Target @ 2R:            ${result.reward_2r:,.4f}")
    print(f"Target @ 3R:            ${result.reward_3r:,.4f}")
    if result.warning:
        print(f"\n[!] WARNING: {result.warning}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Position sizing / risk calculator")
    parser.add_argument("--balance", type=float, help="Account balance in $")
    parser.add_argument("--risk-pct", type=float, help="Risk %% of account for this trade (e.g. 1 for 1%%)")
    parser.add_argument("--entry", type=float, help="Entry price")
    parser.add_argument("--stop", type=float, help="Stop-loss price")
    parser.add_argument("--direction", choices=["long", "short"], default="long",
                         help="Trade direction (default: long)")
    args = parser.parse_args()

    if all(v is not None for v in (args.balance, args.risk_pct, args.entry, args.stop)):
        balance, risk_pct, entry, stop, direction = (
            args.balance, args.risk_pct, args.entry, args.stop, args.direction
        )
    else:
        print("Interactive mode -- enter trade details (Ctrl+C to cancel):\n")
        try:
            balance = float(input("Account balance ($): "))
            risk_pct = float(input("Risk % per trade (e.g. 1 for 1%): "))
            direction = (input("Direction (long/short) [long]: ").strip() or "long")
            entry = float(input("Entry price: "))
            stop = float(input("Stop-loss price: "))
        except (ValueError, KeyboardInterrupt) as exc:
            print(f"\nCancelled or invalid input: {exc}", file=sys.stderr)
            return 1

    try:
        result = position_size(balance, risk_pct, entry, stop, direction)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_result(balance, risk_pct, entry, stop, direction, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
