#!/usr/bin/env python3
"""
Fixup: add PYTHONPATH to _deliver_via_sovereign() in ladybug/monitor.py.

The initial sovereign-delivery patch omitted PYTHONPATH from the subprocess
env, causing ModuleNotFoundError for sovereign_mission_engine when the
subprocess runs.  This patch adds the workspace root to PYTHONPATH so the
subprocess import resolves correctly.

Prerequisite
------------
patch_ladybug_monitor_sovereign_delivery.py must already have been applied
(marker: _deliver_via_sovereign).

Usage
-----
    python scripts/patch_ladybug_monitor_pythonpath.py [--target PATH] [--check]

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
ALREADY_MARKER = "_existing_pp"

OLD_ENV = '    _env = {**_os.environ, "LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1"}'
NEW_ENV = (
    '    _workspace = str(_script.parent.parent)\n'
    '    _existing_pp = _os.environ.get("PYTHONPATH", "")\n'
    '    _pythonpath = f"{_workspace}:{_existing_pp}" if _existing_pp else _workspace\n'
    '    _env = {\n'
    '        **_os.environ,\n'
    '        "LADYBUG_EXECUTABLE_ALERTS_ENABLED": "1",\n'
    '        "PYTHONPATH": _pythonpath,\n'
    '    }'
)


def patch(src: str) -> tuple[str, str]:
    if PREREQ_MARKER not in src:
        raise RuntimeError(
            f"Prerequisite not applied: {PREREQ_MARKER!r} not found. "
            "Run patch_ladybug_monitor_sovereign_delivery.py first."
        )
    if ALREADY_MARKER in src:
        raise RuntimeError(f"Already patched: {ALREADY_MARKER!r} found in target.")
    if OLD_ENV not in src:
        raise RuntimeError(
            "Cannot find expected env-dict line in _deliver_via_sovereign. "
            "The function may have been hand-edited."
        )
    return src.replace(OLD_ENV, NEW_ENV, 1), "PYTHONPATH added to subprocess env"


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
        description="Add PYTHONPATH fix to _deliver_via_sovereign in ladybug/monitor.py"
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

    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".pythonpath_fix_")
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
