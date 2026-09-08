#!/usr/bin/env python3
"""
Patch bitunix_trade_alerts.py to accept a --symbol argument for per-symbol delivery.

Changes applied
---------------
1. Add an argparse block at the top of main() that parses --symbol into
   _symbol_filter (None means scan all, a string means deliver only for
   that base pair).
2. Add a guard at the top of the ranked-loop body so non-target symbols
   are skipped when _symbol_filter is set.

Prerequisite
------------
Both prior patches must already be applied:
  - patch_bitunix_trade_alerts_executable.py  (marker: try_deliver_executable)
  - patch_bitunix_trade_alerts_retest_wiring.py (marker: setup.breakout_level_price)

Usage
-----
    python scripts/patch_bitunix_trade_alerts_symbol_filter.py [--target PATH] [--check]

Safety
------
- Refuses to apply if already patched (idempotent via ALREADY_MARKER).
- Refuses to apply if prereq patches are missing.
- Writes to a temp file then renames (atomic).
- Prints SHA-256 of patched file.

AUTHORIZATION: NONE — read-only analysis system.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

PREREQ_MARKER = "setup.breakout_level_price"
ALREADY_MARKER = "_symbol_filter"

_ARGPARSE_BLOCK = (
    "    import argparse as _ap\n"
    '    _ap_parser = _ap.ArgumentParser(description="Ladybug trade alerts")\n'
    '    _ap_parser.add_argument("--symbol", default=None,'
    ' help="Deliver alerts for this symbol only")\n'
    "    _ap_args = _ap_parser.parse_args()\n"
    "    _symbol_filter = _ap_args.symbol.upper() if _ap_args.symbol else None\n"
)


def patch(src: str) -> tuple[str, str]:
    if PREREQ_MARKER not in src:
        raise RuntimeError(
            f"Prerequisite not applied: {PREREQ_MARKER!r} not found. "
            "Run patch_bitunix_trade_alerts_retest_wiring.py first."
        )
    if ALREADY_MARKER in src:
        raise RuntimeError(f"Already patched: {ALREADY_MARKER!r} found in target.")

    # 1. Inject argparse block at the top of main()
    main_re = re.compile(r"(def main\(\) -> None:\n)", re.MULTILINE)
    if not main_re.search(src):
        raise RuntimeError("Cannot find 'def main() -> None:' in target.")
    src = main_re.sub(r"\1" + _ARGPARSE_BLOCK, src, count=1)

    # 2. Add symbol filter at the top of the ranked loop body.
    #    Capture indentation of the for-line so the injected guard matches
    #    whatever nesting level the loop is at.
    loop_re = re.compile(r"((?P<ind>[ \t]*)for base, [^\n]+in ranked:\n)", re.MULTILINE)
    m = loop_re.search(src)
    if not m:
        raise RuntimeError("Cannot find 'for base, ... in ranked:' loop in target.")
    body_ind = m.group("ind") + "    "
    filter_block = (
        f"{body_ind}if _symbol_filter and base.upper() != _symbol_filter:\n"
        f"{body_ind}    continue\n"
    )
    src = loop_re.sub(r"\1" + filter_block, src, count=1)

    return src, "argparse --symbol + ranked-loop filter added"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _find_target() -> Path:
    candidates = [
        Path.home() / ".openclaw/workspace/sovereign_mission_engine/bitunix_trade_alerts.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate bitunix_trade_alerts.py. Pass --target explicitly."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Add --symbol filter to bitunix_trade_alerts.py"
    )
    ap.add_argument("--target", help="Path to bitunix_trade_alerts.py")
    ap.add_argument("--check", action="store_true", help="Dry-run; print diff only")
    args = ap.parse_args()

    target = Path(args.target) if args.target else _find_target()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        sys.exit(1)

    src = target.read_text(encoding="utf-8")
    try:
        patched, summary = patch(src)
    except RuntimeError as exc:
        print(f"PATCH: SKIP — {exc}")
        sys.exit(0)

    if args.check:
        print(f"DRY-RUN: would apply: {summary}")
        print(f"DRY-RUN: target={target}")
        sys.exit(0)

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".symfilter_")
    try:
        os.write(fd, patched.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    sha = _sha256(patched)
    print("PATCH: PASS")
    print(f"  target : {target}")
    print(f"  changes: {summary}")
    print(f"  sha256 : {sha}")


if __name__ == "__main__":
    main()
