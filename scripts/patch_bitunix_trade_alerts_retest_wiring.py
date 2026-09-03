#!/usr/bin/env python3
"""
Patch _try_executable_delivery() in bitunix_trade_alerts.py to wire in the
retest fields that DeepSetup now provides after the market-scout patch.

Changes applied
---------------
1. Replace the six hardcoded ``None`` values for retest/ATR fields with reads
   from ``setup``:
     breakout_level_price, retest_zone_low, retest_zone_high,
     retest_confirmed, confirmation_candle_closed, atr_15m_price
2. Fix ``scan_timestamp=now.astimezone(timezone.utc)`` — ``now`` is a
   ``time.time()`` float, not a datetime; replace with
   ``datetime.fromtimestamp(now, tz=timezone.utc)``.
3. Add ``datetime`` to the ``from datetime import timezone`` local import so
   the fixed expression is importable.

Prerequisite
------------
patch_bitunix_trade_alerts_executable.py must already have been applied
(marker: ``try_deliver_executable``).

Usage
-----
    python scripts/patch_bitunix_trade_alerts_retest_wiring.py [--target PATH] [--check]

    --target PATH   path to bitunix_trade_alerts.py (default: auto-discovered)
    --check         dry-run; print diff only, do not write

Safety
------
- Refuses to apply if already wired (idempotent).
- Refuses to apply if base patch is missing.
- Writes to a temp file then renames (atomic).
- Prints SHA-256 of patched file.

AUTHORIZATION: NONE — read-only analysis system.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

PREREQ_MARKER = "try_deliver_executable"
ALREADY_MARKER = "setup.breakout_level_price"

# Each entry: (old_exact_string, new_exact_string)
# Ordered so earlier replacements don't break later pattern matches.
_REPLACEMENTS: list[tuple[str, str]] = [
    # 1. breakout_level_price
    (
        "                breakout_level_price=None,       # not in DeepSetup — Gate 6 fails-closed",
        "                breakout_level_price=setup.breakout_level_price if setup else None,",
    ),
    # 2. retest_zone_low
    (
        "                retest_zone_low=None,            # not in DeepSetup — Gate 7 fails-closed",
        "                retest_zone_low=setup.retest_zone_low if setup else None,",
    ),
    # 3. retest_zone_high
    (
        "                retest_zone_high=None,           # not in DeepSetup — Gate 7 fails-closed",
        "                retest_zone_high=setup.retest_zone_high if setup else None,",
    ),
    # 4. retest_confirmed
    (
        "                retest_confirmed=None,           # not in DeepSetup — Gate 8 fails-closed",
        "                retest_confirmed=setup.retest_confirmed if setup else None,",
    ),
    # 5. confirmation_candle_closed
    (
        "                confirmation_candle_closed=None, # not in DeepSetup — Gate 9 fails-closed",
        "                confirmation_candle_closed=setup.confirmation_candle_closed if setup else None,",
    ),
    # 6. atr_15m_price
    (
        "                atr_15m_price=None,              # not in DeepSetup — Gate 12 fails-closed",
        "                atr_15m_price=setup.atr_15m_price if setup else None,",
    ),
    # 7. scan_timestamp — now is float (time.time()), not datetime
    (
        "                scan_timestamp=now.astimezone(timezone.utc) if now else None,",
        "                scan_timestamp=datetime.fromtimestamp(now, tz=timezone.utc) if now else None,",
    ),
    # 8. Add datetime to the local import inside _try_executable_delivery
    (
        "    from datetime import timezone",
        "    from datetime import datetime, timezone",
    ),
]


def patch(src: str) -> tuple[str, str]:
    """Apply all wiring fixes. Returns (patched_src, summary)."""
    if PREREQ_MARKER not in src:
        raise RuntimeError(
            f"Prerequisite patch not applied: {PREREQ_MARKER!r} not found in target. "
            "Run patch_bitunix_trade_alerts_executable.py first."
        )
    if ALREADY_MARKER in src:
        raise RuntimeError(
            f"Already wired: {ALREADY_MARKER!r} found in target."
        )

    applied: list[str] = []
    missing: list[str] = []

    for old, new in _REPLACEMENTS:
        if old in src:
            src = src.replace(old, new, 1)
            applied.append(new.strip()[:60])
        else:
            missing.append(repr(old[:60]))

    if missing:
        raise RuntimeError(
            "Could not find the following expected strings in target — "
            "the file may differ from the expected version:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    return src, f"{len(applied)} substitutions applied"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _find_target() -> Path:
    candidates = [
        Path.home() / ".openclaw/workspace/sovereign_mission_engine/bitunix_trade_alerts.py",
        Path.home() / ".openclaw/workspace/scripts/bitunix_trade_alerts.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate bitunix_trade_alerts.py. Pass --target explicitly."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Wire retest fields into _try_executable_delivery in bitunix_trade_alerts.py"
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

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".retest_wire_")
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
