#!/usr/bin/env python3
"""
journal_triage.py — list all open paper journal entries (no outcome recorded)

Reads paper-journal.json and prints each unresolved setup with its
--record-outcome command ready to copy-paste.

Usage:
    python3 journal_triage.py [--symbol SYMBOL] [--from-date 2026-08-20]

AUTHORIZATION: NONE — read-only audit tool; no exchange access.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

JOURNAL = Path.home() / ".openclaw" / "workspace" / "scripts" / "paper-journal.json"
SCRIPT  = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"


def load_journal() -> dict:
    if not JOURNAL.exists():
        sys.exit(f"Journal not found: {JOURNAL}")
    with open(JOURNAL) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"Unexpected journal format: {type(data).__name__}")
    return data


def stars(entry: dict) -> str:
    return entry.get("stars", "?")


def fmt_entry(date: str, e: dict) -> str:
    sym   = e.get("symbol", "?")
    label = e.get("label", sym)
    dirn  = e.get("direction", "?")
    conf  = e.get("conf", "?")
    entry = e.get("entry", e.get("price", "?"))
    sl    = e.get("sl", "?")
    tp2   = e.get("tp2", "?")
    rr2   = e.get("rr2", "?")
    logged = e.get("logged_at", "")[:16].replace("T", " ")
    arrow = "📈" if dirn == "LONG" else "📉" if dirn == "SHORT" else "  "

    lines = [
        f"  {date}  {sym:<12} {arrow} {dirn:<5}  {stars(e)}  {conf:<4}  "
        f"entry={entry}  sl={sl}  tp2={tp2}  rr={rr2}R  [{logged}]",
        f"    → python3 {SCRIPT} --record-outcome {sym} <outcome> [realized_r mfe mae]",
        f"      outcomes: win | loss | breakeven | void",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="List open paper journal entries")
    parser.add_argument("--symbol", help="Filter by symbol (e.g. BTCUSDT)")
    parser.add_argument("--from-date", dest="from_date",
                        help="Only show entries on or after this date (YYYY-MM-DD)")
    parser.add_argument("--summary", action="store_true",
                        help="Print counts only, no detail")
    args = parser.parse_args()

    journal = load_journal()

    total = 0
    open_entries: list[tuple[str, dict]] = []

    for date in sorted(journal.keys()):
        if args.from_date and date < args.from_date:
            continue
        entries = journal[date]
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            total += 1
            sym = e.get("symbol", "")
            if args.symbol and sym.upper() != args.symbol.upper():
                continue
            if e.get("outcome") is None:
                open_entries.append((date, e))

    closed = total - len(open_entries)

    print(f"\nPAPER JOURNAL TRIAGE  —  {JOURNAL}")
    print(f"  Total entries : {total}")
    print(f"  With outcome  : {closed}")
    print(f"  Open (no outcome): {len(open_entries)}")
    if args.symbol:
        print(f"  Filter: {args.symbol.upper()}")
    print()

    if not open_entries:
        print("  No open entries. All outcomes recorded.")
        return

    if args.summary:
        return

    print("─" * 72)
    for date, e in open_entries:
        print(fmt_entry(date, e))
        print()

    print("─" * 72)
    print(f"  {len(open_entries)} open entries above.")
    print()
    print("  Outcome key:")
    print("    win        — trade hit TP2 or manually exited in profit")
    print("    loss       — trade hit SL")
    print("    breakeven  — exited near entry (moved SL to entry)")
    print("    void       — setup invalidated before entry; never took")
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
