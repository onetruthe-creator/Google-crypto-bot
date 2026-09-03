#!/usr/bin/env python3
"""
Patch bitunix_market_scout.py to wire in ladybug_retest_detector.

Changes applied
---------------
1. Add 6 new Optional fields to DeepSetup after quote_volume_24h.
2. Inject import for detect_retest after the last sovereign_mission_engine import.
3. After ``atr = _atr_pct(candles)`` in analyze_symbol(), add the retest
   detection call and ATR price computation.
4. Extend the DeepSetup(**) constructor call with the new fields, anchored
   on ``quote_volume_24h=``.

Usage
-----
    python scripts/patch_bitunix_market_scout_retest.py [--target PATH] [--check]

    --target PATH   path to bitunix_market_scout.py (default: auto-discovered)
    --check         dry-run; print diff only, do not write

Safety
------
- Refuses to apply if already patched (idempotent).
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

ALREADY_MARKER = "ladybug_retest_detector"

# ── Anchor patterns ────────────────────────────────────────────────────────────

# 1. DeepSetup field insertion point: after `    quote_volume_24h: float = 0.0`
DEEPSETUP_FIELD_ANCHOR = re.compile(
    r'([ \t]+quote_volume_24h\s*:\s*float\s*=\s*0\.0\s*\n)',
    re.MULTILINE,
)
DEEPSETUP_FIELD_INSERTION = (
    "    breakout_level_price: Optional[float] = None\n"
    "    retest_zone_low: Optional[float] = None\n"
    "    retest_zone_high: Optional[float] = None\n"
    "    retest_confirmed: Optional[bool] = None\n"
    "    confirmation_candle_closed: Optional[bool] = None\n"
    "    atr_15m_price: Optional[float] = None\n"
)

# 2. Import injection: after the last line matching `from sovereign_mission_engine...`
SME_IMPORT_RE = re.compile(
    r'^(from sovereign_mission_engine\.[^\n]+)\n',
    re.MULTILINE,
)
IMPORT_INJECTION = (
    "from sovereign_mission_engine.ladybug_retest_detector import detect_retest\n"
)

# 3. Retest call: after `atr = _atr_pct(candles)`
ATR_ANCHOR = re.compile(
    r'([ \t]+atr\s*=\s*_atr_pct\(candles\)\s*\n)',
    re.MULTILINE,
)
RETEST_CALL_TEMPLATE = (
    "{indent}_retest = detect_retest(\n"
    "{indent}    candles, direction=direction, last_price=last, atr_pct=atr\n"
    "{indent})\n"
    "{indent}_atr_15m_price = last * (atr / 100.0)\n"
)

# 4. Constructor: extend `quote_volume_24h=<expr>,` inside DeepSetup(...)
CONSTRUCTOR_ANCHOR = re.compile(
    r'([ \t]+quote_volume_24h\s*=\s*[^\n,]+,\s*\n)',
    re.MULTILINE,
)
CONSTRUCTOR_INSERTION = (
    "        breakout_level_price=_retest.breakout_level_price,\n"
    "        retest_zone_low=_retest.retest_zone_low,\n"
    "        retest_zone_high=_retest.retest_zone_high,\n"
    "        retest_confirmed=_retest.retest_confirmed,\n"
    "        confirmation_candle_closed=_retest.confirmation_candle_closed,\n"
    "        atr_15m_price=_atr_15m_price,\n"
)


# ── Optional[...] import guard ──────────────────────────────────────────────────

def _ensure_optional_imported(src: str) -> str:
    """Add Optional to the typing import if it isn't already there."""
    if "Optional" in src:
        return src  # already available

    # Try to extend an existing `from typing import ...` line.
    typing_re = re.compile(r'^(from typing import )([^\n]+)', re.MULTILINE)
    m = typing_re.search(src)
    if m:
        existing = m.group(2)
        if "Optional" not in existing:
            return src[:m.start(2)] + "Optional, " + existing + src[m.end(2):]
        return src

    # No typing import — insert one at the top, after any __future__ import.
    future_re = re.compile(r'^(from __future__ import[^\n]+\n)', re.MULTILINE)
    fm = future_re.search(src)
    if fm:
        insert_at = fm.end()
        return src[:insert_at] + "from typing import Optional\n" + src[insert_at:]

    # Fallback: insert at the very beginning.
    return "from typing import Optional\n" + src


# ── Patch ──────────────────────────────────────────────────────────────────────

def _show_context(src: str, pattern: str) -> str:
    lines = src.splitlines()
    hits = [
        f"  {i+1:4d}: {l}"
        for i, l in enumerate(lines)
        if pattern.lower() in l.lower()
    ]
    return "\n".join(hits) if hits else "  (none found)"


def patch(src: str) -> tuple[str, str]:
    """Apply all four changes. Returns (patched_src, summary_str)."""
    if ALREADY_MARKER in src:
        raise RuntimeError(
            f"Already patched: {ALREADY_MARKER!r} already present in target."
        )

    changes: list[str] = []

    # ── 1. Optional import guard ──────────────────────────────────────────────
    src = _ensure_optional_imported(src)

    # ── 2. DeepSetup fields ───────────────────────────────────────────────────
    m1 = DEEPSETUP_FIELD_ANCHOR.search(src)
    if m1 is None:
        lines_ctx = _show_context(src, "quote_volume_24h")
        raise RuntimeError(
            "Cannot find DeepSetup field anchor "
            "(    quote_volume_24h: float = 0.0).\n"
            f"Lines matching 'quote_volume_24h':\n{lines_ctx}"
        )
    # Insert the new fields immediately after the matched line.
    pos = m1.end()
    src = src[:pos] + DEEPSETUP_FIELD_INSERTION + src[pos:]
    changes.append("DeepSetup fields (+6)")

    # ── 3. Import injection ───────────────────────────────────────────────────
    # Find the last SME import and insert our import after it.
    all_matches = list(SME_IMPORT_RE.finditer(src))
    if not all_matches:
        raise RuntimeError(
            "Cannot find any 'from sovereign_mission_engine...' import in target."
        )
    last_m = all_matches[-1]
    pos = last_m.end()
    src = src[:pos] + IMPORT_INJECTION + src[pos:]
    changes.append("import detect_retest")

    # ── 4. Retest detection call ──────────────────────────────────────────────
    m3 = ATR_ANCHOR.search(src)
    if m3 is None:
        lines_ctx = _show_context(src, "_atr_pct")
        raise RuntimeError(
            "Cannot find ATR anchor (atr = _atr_pct(candles)).\n"
            f"Lines matching '_atr_pct':\n{lines_ctx}"
        )
    indent = re.match(r'([ \t]*)', m3.group(0)).group(1)
    call_block = RETEST_CALL_TEMPLATE.format(indent=indent)
    pos = m3.end()
    src = src[:pos] + call_block + src[pos:]
    changes.append("detect_retest() call + _atr_15m_price")

    # ── 5. Constructor extension ───────────────────────────────────────────────
    # We need the SECOND occurrence of `quote_volume_24h=` — the first is the
    # class-field definition we just inserted (it has a colon), not the
    # constructor keyword argument. We search for `quote_volume_24h=` WITHOUT
    # a preceding colon to target the constructor call.
    constructor_re = re.compile(
        r'([ \t]+quote_volume_24h\s*=\s*[^\n,]+,[ \t]*\n)',
        re.MULTILINE,
    )
    # The field definition has a colon before =, the constructor arg does not.
    # Filter to the one that is NOT a type-annotation line.
    ctor_match = None
    for cm in constructor_re.finditer(src):
        line = cm.group(0)
        # Type-annotation lines look like `quote_volume_24h: float = 0.0`
        # Constructor lines look like `quote_volume_24h=some_var,`
        if ":" not in line.split("quote_volume_24h")[0].split("\n")[-1]:
            ctor_match = cm
            break  # take the first constructor-style match
    if ctor_match is None:
        lines_ctx = _show_context(src, "quote_volume_24h")
        raise RuntimeError(
            "Cannot find quote_volume_24h= constructor argument.\n"
            f"Lines matching 'quote_volume_24h':\n{lines_ctx}"
        )
    pos = ctor_match.end()
    src = src[:pos] + CONSTRUCTOR_INSERTION + src[pos:]
    changes.append("DeepSetup constructor (+6 fields)")

    summary = "; ".join(changes)
    return src, summary


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _find_target() -> Path:
    candidates = [
        Path.home() / ".openclaw/workspace/sovereign_mission_engine/bitunix_market_scout.py",
        Path.home() / ".openclaw/workspace/scripts/bitunix_market_scout.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate bitunix_market_scout.py. Pass --target explicitly."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch bitunix_market_scout.py for retest detection")
    ap.add_argument("--target", help="Path to bitunix_market_scout.py")
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

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".scout_patch_")
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
