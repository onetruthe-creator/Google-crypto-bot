#!/usr/bin/env python3
"""
fix_sme_path.py — wire sovereign_mission_engine into crypto-signals.py's import path

sovereign_mission_engine/ lives at ~/.openclaw/workspace/ (one level above scripts/).
This patch inserts a sys.path.insert() near the top of crypto-signals.py so the
package is importable however the script is invoked (cron, OpenClaw, direct).

AUTHORIZATION: NONE — path-wiring only; no orders placed.
"""
from __future__ import annotations
import hashlib, os, subprocess, sys
from pathlib import Path

TARGET = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"
SME_DIR = Path.home() / ".openclaw" / "workspace" / "sovereign_mission_engine"

# Inserted block — uses only stdlib, no external deps at insertion time.
_PATH_BLOCK = (
    '# sovereign_mission_engine path — workspace root one level above scripts/\n'
    'import os as _os, sys as _sys\n'
    '_SME_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))\n'
    'if _SME_ROOT not in _sys.path:\n'
    '    _sys.path.insert(0, _SME_ROOT)\n'
    'del _os, _sys, _SME_ROOT\n'
    '\n'
)

ANCHOR = 'DO_SCAN="--scan" in sys.argv\n'
ALREADY_MARKER = '_SME_ROOT'


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def abort(msg: str) -> None:
    print(f"\nABORT — {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("fix_sme_path.py — add sovereign_mission_engine to sys.path")
    print("=" * 58)

    if not TARGET.exists():
        abort(f"Target not found: {TARGET}")

    if not SME_DIR.exists():
        abort(
            f"sovereign_mission_engine not found at: {SME_DIR}\n"
            "Check that the package directory exists before running this patch."
        )
    if not (SME_DIR / "__init__.py").exists():
        abort(
            f"{SME_DIR} exists but has no __init__.py — "
            "may not be a valid Python package."
        )

    src = TARGET.read_text(encoding="utf-8")

    if ALREADY_MARKER in src:
        print("  Already applied — nothing to do.")
        return

    if ANCHOR not in src:
        abort(
            f"Anchor {ANCHOR!r} not found in {TARGET}.\n"
            "The file may differ from expected state."
        )

    print(f"  Before SHA-256: {sha256_of(TARGET)}")
    print(f"  SME package:    {SME_DIR}")

    patched = src.replace(ANCHOR, _PATH_BLOCK + ANCHOR, 1)

    tmp = TARGET.with_suffix(".fixsme_tmp")
    try:
        tmp.write_text(patched, encoding="utf-8")
        tmp.chmod(0o755)
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(tmp)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            tmp.unlink(missing_ok=True)
            abort(f"Compile check FAILED:\n{result.stderr}")
        os.replace(tmp, TARGET)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        abort(f"Write error: {exc}")

    print(f"  After  SHA-256: {sha256_of(TARGET)}")
    print()
    # Quick import test
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sovereign_mission_engine",
        str(SME_DIR / "__init__.py"),
    )
    if spec is not None:
        print(f"  Import check:   sovereign_mission_engine importable from {SME_DIR.parent}")
    print()
    print("PATCH: PASS — sovereign_mission_engine now on sys.path for crypto-signals.py")
    print()
    print("Verify:")
    print(f"  python3 {TARGET} --scan")
    print("  (CLOSED-LOOP STATE should no longer show UNAVAILABLE / ModuleNotFoundError)")
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
