#!/usr/bin/env python3
"""
Fixup: replace direct-path subprocess call with -m module invocation
in _deliver_via_sovereign() in ladybug/monitor.py.

Problem
-------
The initial sovereign-delivery patch called bitunix_trade_alerts.py by its
absolute filesystem path:

    _sp.run([_sys.executable, str(_script), "--symbol", symbol], ...)

This fails with:
    ImportError: attempted relative import with no known parent package

because bitunix_trade_alerts.py uses relative imports (.bitunix_runtime,
.lb_sabbath_guard, etc.) that only resolve when the module is run as part of
a package via -m.

Fix
---
Replace the direct-path call with a -m module invocation and add cwd= so
Python finds the package root:

    _sp.run(
        [_sys.executable, "-m", "sovereign_mission_engine.bitunix_trade_alerts",
         "--symbol", symbol],
        cwd=str(_script.parent.parent),
        env=_env,
        timeout=120,
    )

Prerequisite
------------
_deliver_via_sovereign must already be present in the target
(run patch_ladybug_monitor_sovereign_delivery.py first).

Usage
-----
    python scripts/patch_ladybug_monitor_m_invocation.py [--target PATH] [--check]

AUTHORIZATION: NONE — read-only analysis system.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

PREREQ_MARKER = "_deliver_via_sovereign"
ALREADY_MARKER = "sovereign_mission_engine.bitunix_trade_alerts"

OLD_RUN = (
    "        _sp.run(\n"
    "            [_sys.executable, str(_script), \"--symbol\", symbol],\n"
    "            env=_env,\n"
    "            timeout=120,\n"
    "        )"
)
NEW_RUN = (
    "        _sp.run(\n"
    "            [_sys.executable, \"-m\", \"sovereign_mission_engine.bitunix_trade_alerts\",\n"
    "             \"--symbol\", symbol],\n"
    "            cwd=str(_script.parent.parent),\n"
    "            env=_env,\n"
    "            timeout=120,\n"
    "        )"
)

# Also handle the single-line variant that the pythonpath patch may have left
OLD_RUN_ONELINE = (
    "        _sp.run(\n"
    "            [_sys.executable, str(_script), \"--symbol\", symbol],\n"
    "            env=_env, timeout=120,\n"
    "        )"
)
NEW_RUN_ONELINE = NEW_RUN


def patch(src: str) -> tuple[str, str]:
    if PREREQ_MARKER not in src:
        raise RuntimeError(
            f"Prerequisite not applied: {PREREQ_MARKER!r} not found. "
            "Run patch_ladybug_monitor_sovereign_delivery.py first."
        )
    if ALREADY_MARKER in src:
        raise RuntimeError(
            f"Already patched: {ALREADY_MARKER!r} found — -m invocation already present."
        )

    # Try canonical multi-line form first
    if OLD_RUN in src:
        return src.replace(OLD_RUN, NEW_RUN, 1), "-m module invocation wired (multi-line)"

    # Try one-liner variant
    if OLD_RUN_ONELINE in src:
        return (
            src.replace(OLD_RUN_ONELINE, NEW_RUN_ONELINE, 1),
            "-m module invocation wired (one-liner)",
        )

    raise RuntimeError(
        "Cannot find expected _sp.run([_sys.executable, str(_script), ...]) pattern.\n"
        "The function may have been hand-edited. Inspect _deliver_via_sovereign manually."
    )


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
        description="Replace direct-path subprocess call with -m invocation in _deliver_via_sovereign"
    )
    ap.add_argument("--target", help="Path to ladybug/monitor.py")
    ap.add_argument("--check", action="store_true", help="Dry-run; print what would change")
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

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".m_invocation_fix_")
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
