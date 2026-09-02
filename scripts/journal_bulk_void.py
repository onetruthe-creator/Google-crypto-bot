#!/usr/bin/env python3
"""
journal_bulk_void.py — mark all open journal entries as 'void' in one pass

Marks every entry with no recorded outcome as outcome="void".
After running, use --record-outcome to correct the entries you
actually entered:

    python3 crypto-signals.py --record-outcome BTCUSDT win 2.1 3.0 0.8
    python3 crypto-signals.py --record-outcome ETHUSDT loss

USAGE:
    python3 journal_bulk_void.py [--dry-run]

    --dry-run   print what would change without writing anything

AUTHORIZATION: NONE — journal audit only; no exchange access.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

JOURNAL = Path.home() / ".openclaw" / "workspace" / "scripts" / "paper-journal.json"


def load() -> dict:
    if not JOURNAL.exists():
        sys.exit(f"Journal not found: {JOURNAL}")
    with open(JOURNAL) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"Unexpected journal format: {type(data).__name__}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-mark open journal entries as void"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing"
    )
    parser.add_argument(
        "--from-date", dest="from_date",
        help="Only void entries on or after this date (YYYY-MM-DD)"
    )
    args = parser.parse_args()

    journal = load()
    now_ts = datetime.now(timezone.utc).isoformat()

    voided = 0
    already = 0

    for date in sorted(journal.keys()):
        if args.from_date and date < args.from_date:
            continue
        entries = journal[date]
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("outcome") is None:
                sym = e.get("symbol", "?")
                logged = e.get("logged_at", "")[:16]
                if args.dry_run:
                    print(f"  would void: {date}  {sym:<14} [{logged}]")
                else:
                    e["outcome"] = "void"
                    e["outcome_ts"] = now_ts
                voided += 1
            else:
                already += 1

    print(f"\nJOURNAL BULK-VOID")
    print(f"  Already recorded : {already}")
    print(f"  Open entries     : {voided}")

    if voided == 0:
        print("  Nothing to void.")
        return

    if args.dry_run:
        print(f"\n  DRY RUN — {voided} entries would be marked void.")
        print("  Re-run without --dry-run to apply.")
        return

    # Atomic write
    tmp = str(JOURNAL) + ".bulkvoid_tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(journal, f, indent=2)
        os.replace(tmp, str(JOURNAL))
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        sys.exit(f"Write failed: {exc}")

    print(f"\n  {voided} entries marked void  →  {JOURNAL}")
    print()
    print("  To correct entries you actually traded:")
    print("    python3 ~/.openclaw/workspace/scripts/crypto-signals.py \\")
    print("        --record-outcome SYMBOL win|loss|breakeven [realized_r mfe mae]")
    print()
    print("  Note: --record-outcome overwrites the most recent open (void) entry")
    print("  for that symbol. Run it once per symbol you actually entered.")
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
