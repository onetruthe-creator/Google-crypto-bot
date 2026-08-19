#!/usr/bin/env python3
"""
Generates a synthetic daily OHLCV CSV for practicing with backtest.py.

This is FAKE data (a seeded random walk with drift/regime changes) meant only
to let you exercise the backtest tool's mechanics. Replace it with real
historical data from your broker/data provider before drawing any real
conclusions about a strategy.

Usage:
    python3 generate_sample_data.py --out ../sample_data/sample_ohlcv.csv --days 500
"""
import argparse
import csv
import datetime
import random


def generate(days: int, seed: int, start_price: float):
    random.seed(seed)
    rows = []
    price = start_price
    date = datetime.date(2024, 1, 1)

    # Alternate between trending-up, trending-down, and choppy regimes so the
    # sample data actually contains crossover setups to backtest against.
    regime_len = 40
    drift_cycle = [0.006, -0.004, 0.0005, 0.005]

    for i in range(days):
        regime = drift_cycle[(i // regime_len) % len(drift_cycle)]
        daily_return = regime + random.gauss(0, 0.012)
        open_p = price
        close_p = max(0.5, open_p * (1 + daily_return))
        high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, 0.004)))
        low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, 0.004)))
        volume = int(random.gauss(1_000_000, 150_000))

        rows.append({
            "Date": date.isoformat(),
            "Open": round(open_p, 4),
            "High": round(high_p, 4),
            "Low": round(low_p, 4),
            "Close": round(close_p, 4),
            "Volume": max(volume, 0),
        })

        price = close_p
        date += datetime.timedelta(days=1)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic OHLCV sample data")
    parser.add_argument("--out", default="../sample_data/sample_ohlcv.csv")
    parser.add_argument("--days", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-price", type=float, default=100.0)
    args = parser.parse_args()

    rows = generate(args.days, args.seed, args.start_price)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Open", "High", "Low", "Close", "Volume"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows of synthetic data to {args.out}")


if __name__ == "__main__":
    main()
