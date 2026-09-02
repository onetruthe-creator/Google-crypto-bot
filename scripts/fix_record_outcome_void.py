#!/usr/bin/env python3
"""
fix_record_outcome_void.py — allow --record-outcome to overwrite 'void' entries

After a bulk-void pass, all open entries have outcome="void".
The original code only finds entries where outcome is None.
This patch expands the match to include outcome=="void" so a real
trade result can override a voided entry.

AUTHORIZATION: NONE — journal audit fix only; no exchange access.
"""
from __future__ import annotations
import hashlib, os, subprocess, sys
from pathlib import Path

TARGET = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"

OLD = (
    '            and e.get("outcome") is None\n'
)
NEW = (
    '            and e.get("outcome") in (None, "void")\n'
)
ALREADY_MARKER = 'in (None, "void")'


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def abort(msg: str) -> None:
    print(f"\nABORT — {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print('fix_record_outcome_void.py — expand --record-outcome to match void entries')
    print("=" * 72)

    if not TARGET.exists():
        abort(f"Target not found: {TARGET}")

    src = TARGET.read_text(encoding="utf-8")

    if ALREADY_MARKER in src:
        print("  Already applied — nothing to do.")
        return

    if OLD not in src:
        abort(
            f"Anchor not found:\n  {OLD!r}\n"
            "File may differ from expected state."
        )

    print(f"  Before SHA-256: {sha256_of(TARGET)}")
    patched = src.replace(OLD, NEW, 1)

    tmp = TARGET.with_suffix(".fixrov_tmp")
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
    print("PATCH: PASS — --record-outcome now matches void entries")
    print()
    print("Test:")
    print("  python3 ~/.openclaw/workspace/scripts/crypto-signals.py --record-outcome CAKEUSDT win 2.1 3.0 0.8")
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
