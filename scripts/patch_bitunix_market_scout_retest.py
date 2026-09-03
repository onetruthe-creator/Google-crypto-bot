#!/usr/bin/env python3
"""
Patch bitunix_market_scout.py to wire in ladybug_retest_detector.

Changes applied
---------------
1. Add 6 new Optional fields to DeepSetup after quote_volume_24h.
2. Inject ``from sovereign_mission_engine.ladybug_retest_detector import detect_retest``
   after the last top-level import in the file.
3. Insert the retest detection call and _atr_15m_price computation
   immediately BEFORE the ``return DeepSetup(...)`` statement.
4. Add the 6 new keyword arguments inside the DeepSetup(...) constructor
   call, just before its closing parenthesis.

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

IMPORT_INJECTION = (
    "from sovereign_mission_engine.ladybug_retest_detector import detect_retest\n"
)

DEEPSETUP_FIELD_SUFFIX = (
    "    breakout_level_price: Optional[float] = None\n"
    "    retest_zone_low: Optional[float] = None\n"
    "    retest_zone_high: Optional[float] = None\n"
    "    retest_confirmed: Optional[bool] = None\n"
    "    confirmation_candle_closed: Optional[bool] = None\n"
    "    atr_15m_price: Optional[float] = None\n"
)

# Inserted BEFORE `return DeepSetup(` — note {indent} placeholder.
RETEST_CALL_TEMPLATE = (
    "{indent}_retest = detect_retest(\n"
    "{indent}    candles, direction=direction, last_price=last, atr_pct=atr\n"
    "{indent})\n"
    "{indent}_atr_15m_price = last * (atr / 100.0)\n"
)

# Inserted just before the closing `)` of the DeepSetup(...) call.
CONSTRUCTOR_SUFFIX = (
    "        breakout_level_price=_retest.breakout_level_price,\n"
    "        retest_zone_low=_retest.retest_zone_low,\n"
    "        retest_zone_high=_retest.retest_zone_high,\n"
    "        retest_confirmed=_retest.retest_confirmed,\n"
    "        confirmation_candle_closed=_retest.confirmation_candle_closed,\n"
    "        atr_15m_price=_atr_15m_price,\n"
)

# ── Patterns ────────────────────────────────────────────────────────────────────

# DeepSetup dataclass field insertion anchor.
DEEPSETUP_FIELD_ANCHOR = re.compile(
    r'([ \t]+quote_volume_24h\s*:\s*float\s*=\s*0\.0[ \t]*\n)',
    re.MULTILINE,
)

# `return DeepSetup(` — used to anchor both the retest call and the constructor.
DEEPSETUP_RETURN_RE = re.compile(
    r'([ \t]+)(return\s+DeepSetup\()',
    re.MULTILINE,
)

# Top-level import lines (no leading whitespace).
TOP_IMPORT_RE = re.compile(
    r'^((?:from|import)\s+[^\n]+)\n',
    re.MULTILINE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _context_lines(src: str, keyword: str, radius: int = 2) -> str:
    lines = src.splitlines()
    hits = []
    for i, l in enumerate(lines):
        if keyword.lower() in l.lower():
            snippet = "\n".join(
                f"  {j+1:5d}: {lines[j]}"
                for j in range(max(0, i - radius), min(len(lines), i + radius + 1))
            )
            hits.append(snippet)
    return ("\n---\n".join(hits)) if hits else "  (none found)"


def _ensure_optional_imported(src: str) -> str:
    """Guarantee ``Optional`` is importable in the module."""
    if re.search(r'\bOptional\b', src):
        return src  # already present

    # Extend an existing `from typing import ...` line.
    typing_re = re.compile(r'^(from typing import )([^\n]+)', re.MULTILINE)
    m = typing_re.search(src)
    if m and "Optional" not in m.group(2):
        return src[:m.start(2)] + "Optional, " + m.group(2) + src[m.end(2):]
    if m:
        return src

    # No typing import at all — add one after any __future__ import.
    future_m = re.search(r'^from __future__ import[^\n]+\n', src, re.MULTILINE)
    if future_m:
        p = future_m.end()
        return src[:p] + "from typing import Optional\n" + src[p:]

    # Last resort: prepend to file.
    return "from typing import Optional\n" + src


def _find_import_insertion_point(src: str) -> int:
    """
    Return the character position just AFTER the last top-level import line.
    Preference order:
      1. last ``from sovereign_mission_engine...`` line
      2. last ``from bitunix_...`` line
      3. last top-level ``from ...`` or ``import ...`` line
    """
    # Strategy 1 — SME imports
    sme_re = re.compile(r'^from sovereign_mission_engine\.[^\n]+\n', re.MULTILINE)
    matches = list(sme_re.finditer(src))
    if matches:
        return matches[-1].end()

    # Strategy 2 — bitunix_ imports
    bx_re = re.compile(r'^from bitunix_[^\n]+\n', re.MULTILINE)
    matches = list(bx_re.finditer(src))
    if matches:
        return matches[-1].end()

    # Strategy 3 — any top-level import
    matches = list(TOP_IMPORT_RE.finditer(src))
    if matches:
        return matches[-1].end()

    return -1


def _find_deepsetup_return(src: str):
    """Return the re.Match for the first ``return DeepSetup(`` statement."""
    return DEEPSETUP_RETURN_RE.search(src)


def _find_constructor_close(src: str, open_pos: int) -> int:
    """
    Starting from open_pos (the character AFTER the opening ``(`` of DeepSetup),
    find the matching closing ``)`` and return its index in src.
    """
    depth = 1
    i = open_pos
    while i < len(src) and depth > 0:
        ch = src[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        i += 1
    return i - 1  # position of the matching `)`


# ── Main patch logic ──────────────────────────────────────────────────────────────

def patch(src: str) -> tuple[str, str]:
    """Apply all four changes. Returns (patched_src, human_readable_summary)."""
    if ALREADY_MARKER in src:
        raise RuntimeError(
            f"Already patched: {ALREADY_MARKER!r} found in target."
        )

    changes: list[str] = []

    # ── 0. Ensure Optional is importable ─────────────────────────────────────
    src = _ensure_optional_imported(src)

    # ── 1. DeepSetup field additions ─────────────────────────────────────────
    m1 = DEEPSETUP_FIELD_ANCHOR.search(src)
    if m1 is None:
        ctx = _context_lines(src, "quote_volume_24h")
        raise RuntimeError(
            "Cannot find DeepSetup field anchor (quote_volume_24h: float = 0.0).\n"
            f"Context around 'quote_volume_24h':\n{ctx}"
        )
    pos = m1.end()
    src = src[:pos] + DEEPSETUP_FIELD_SUFFIX + src[pos:]
    changes.append("DeepSetup fields (+6)")

    # ── 2. Import injection ───────────────────────────────────────────────────
    imp_pos = _find_import_insertion_point(src)
    if imp_pos < 0:
        raise RuntimeError(
            "Cannot find any top-level import statement to anchor the "
            "detect_retest import. Please add it manually:\n"
            f"  {IMPORT_INJECTION.strip()}"
        )
    src = src[:imp_pos] + IMPORT_INJECTION + src[imp_pos:]
    changes.append("import detect_retest")

    # ── 3. Retest call before `return DeepSetup(` ────────────────────────────
    m3 = _find_deepsetup_return(src)
    if m3 is None:
        ctx = _context_lines(src, "DeepSetup")
        raise RuntimeError(
            "Cannot find 'return DeepSetup(' in target.\n"
            f"Context around 'DeepSetup':\n{ctx}"
        )
    indent = m3.group(1)
    call_block = RETEST_CALL_TEMPLATE.format(indent=indent)
    insert_at = m3.start()
    src = src[:insert_at] + call_block + src[insert_at:]
    changes.append("detect_retest() call + _atr_15m_price")

    # ── 4. Constructor field additions ────────────────────────────────────────
    # Re-find the (now-shifted) `return DeepSetup(` after the insertion above.
    m4 = _find_deepsetup_return(src)
    if m4 is None:
        raise RuntimeError("Could not re-locate 'return DeepSetup(' after retest call insertion.")
    # Position just after the opening `(`
    open_paren_pos = m4.end()  # end() is one past the matched `(`
    close_paren_pos = _find_constructor_close(src, open_paren_pos)

    # Find the last non-whitespace character before the closing `)` to insert after.
    before_close = src[:close_paren_pos].rstrip()
    trailing = src[len(before_close):close_paren_pos]  # whitespace we'll restore

    # Ensure there's a trailing comma on the last existing argument.
    if before_close and not before_close.endswith(','):
        src = before_close + ",\n" + CONSTRUCTOR_SUFFIX + trailing + src[close_paren_pos:]
    else:
        src = before_close + "\n" + CONSTRUCTOR_SUFFIX + trailing + src[close_paren_pos:]
    changes.append("DeepSetup constructor (+6 fields)")

    return src, "; ".join(changes)


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
