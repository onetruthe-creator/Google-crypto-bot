#!/usr/bin/env python3
"""
Patch ladybug/monitor.py to call sovereign delivery when a symbol is CONFIRMED.

Changes applied
---------------
1. Append _deliver_via_sovereign() to the module.  This function calls
   bitunix_trade_alerts.py as a subprocess with --symbol <symbol> and
   LADYBUG_EXECUTABLE_ALERTS_ENABLED=1, so the full 24-gate validation
   runs before any Telegram relay.
2. Insert _deliver_via_sovereign(symbol) immediately after the
   CONFIRMED_ANALYSIS log line so sovereign delivery fires on every
   confirmed symbol.

Prerequisite
------------
patch_bitunix_trade_alerts_symbol_filter.py must already have been applied
to bitunix_trade_alerts.py (marker: _symbol_filter).
ladybug/monitor.py must already contain the CONFIRMED_ANALYSIS log line
(marker: CONFIRMED_ANALYSIS sent (AUTHORIZATION: NONE)).

Usage
-----
    python scripts/patch_ladybug_monitor_sovereign_delivery.py [--target PATH] [--check]

Safety
------
- Refuses to apply if already patched (idempotent).
- Refuses to apply if the CONFIRMED_ANALYSIS anchor is missing.
- Writes atomically via temp-file rename.
- Prints SHA-256 of patched file.

AUTHORIZATION: NONE — delivery gated by LADYBUG_EXECUTABLE_ALERTS_ENABLED.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

PREREQ_MARKER = "CONFIRMED_ANALYSIS sent (AUTHORIZATION: NONE)"
ALREADY_MARKER = "_deliver_via_sovereign"

_SOVEREIGN_FUNCTION = '''

def _deliver_via_sovereign(symbol: str) -> None:
    """Trigger a full sovereign scan + 24-gate delivery for a confirmed symbol.

    Calls sovereign_mission_engine/bitunix_trade_alerts.py as a subprocess
    with --symbol <symbol> and LADYBUG_EXECUTABLE_ALERTS_ENABLED=1.
    The subprocess does a live market fetch, scores the symbol, and runs
    all 24 gates before any Telegram relay.

    AUTHORIZATION: NONE — actual relay gated by LADYBUG_EXECUTABLE_ALERTS_ENABLED.
    """
    import logging as _logging
    import os as _os
    import subprocess as _sp
    import sys as _sys
    from pathlib import Path as _Path

    _script = (
        _Path(__file__).resolve().parent.parent
        / "sovereign_mission_engine"
        / "bitunix_trade_alerts.py"
    )
    if not _script.exists():
        _logging.getLogger(__name__).warning(
            "sovereign delivery script not found: %s", _script
        )
        return
    _env = {**_os.environ, "LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}
    try:
        _sp.run(
            [_sys.executable, str(_script), "--symbol", symbol],
            env=_env,
            timeout=120,
        )
    except Exception as _exc:
        _logging.getLogger(__name__).warning(
            "sovereign delivery error for %s: %s", symbol, _exc
        )
'''


def patch(src: str) -> tuple[str, str]:
    if PREREQ_MARKER not in src:
        raise RuntimeError(
            f"Prerequisite not found: {PREREQ_MARKER!r} not in target. "
            "Is this the right ladybug/monitor.py?"
        )
    if ALREADY_MARKER in src:
        raise RuntimeError(f"Already patched: {ALREADY_MARKER!r} found in target.")

    # 1. Insert the sovereign-delivery call after the CONFIRMED_ANALYSIS log line.
    #    Capture the leading indent so the call matches the surrounding code.
    confirmed_re = re.compile(
        r'((?P<ind>[ \t]*)logger\.info\("[^"]*CONFIRMED_ANALYSIS sent'
        r' \(AUTHORIZATION: NONE\)[^"]*",\s*symbol\))'
    )
    m = confirmed_re.search(src)
    if not m:
        raise RuntimeError(
            "Cannot find logger.info CONFIRMED_ANALYSIS line in target."
        )
    indent = m.group("ind")
    call_line = f"\n{indent}_deliver_via_sovereign(symbol)"
    src = confirmed_re.sub(r"\1" + call_line, src, count=1)

    # 2. Append the _deliver_via_sovereign function at end of file.
    src = src.rstrip("\n") + "\n" + _SOVEREIGN_FUNCTION

    return src, "_deliver_via_sovereign added and wired at CONFIRMED"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _find_target() -> Path:
    candidates = [
        Path.home() / ".openclaw/workspace/ladybug/monitor.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate ladybug/monitor.py. Pass --target explicitly."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Wire sovereign delivery into ladybug/monitor.py at CONFIRMED"
    )
    ap.add_argument("--target", help="Path to ladybug/monitor.py")
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

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".sovereign_wire_")
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
