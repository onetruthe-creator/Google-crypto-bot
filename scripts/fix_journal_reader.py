#!/usr/bin/env python3
"""
fix_journal_reader.py — patch _do_record_outcome() to handle the actual
paper-journal.json format: {date_str: [entry, ...]} dict-of-date-buckets.

AUTHORIZATION: NONE — read-only fix; no orders placed.
"""
from __future__ import annotations
import hashlib, os, subprocess, sys, tempfile
from pathlib import Path

TARGET = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"

OLD = (
    '    if not isinstance(journal, list):\n'
    '        print("RECORD_OUTCOME_ERROR: journal root is not a JSON array")\n'
    '        return\n'
    '    # Find the most recent open entry for this symbol (outcome still null).\n'
    '    target = next(\n'
    '        (\n'
    '            e for e in reversed(journal)\n'
    '            if isinstance(e, dict)\n'
    '            and e.get("symbol") == symbol\n'
    '            and e.get("outcome") is None\n'
    '        ),\n'
    '        None,\n'
    '    )'
)

NEW = (
    '    # Journal is a dict keyed by date string; each value is a list of entries.\n'
    '    if isinstance(journal, list):\n'
    '        entries_iter = journal\n'
    '    elif isinstance(journal, dict):\n'
    '        entries_iter = []\n'
    '        for day_entries in journal.values():\n'
    '            if isinstance(day_entries, list):\n'
    '                entries_iter.extend(day_entries)\n'
    '    else:\n'
    '        print("RECORD_OUTCOME_ERROR: unrecognized journal format")\n'
    '        return\n'
    '    # Find the most recent open entry for this symbol (outcome still null).\n'
    '    target = next(\n'
    '        (\n'
    '            e for e in reversed(entries_iter)\n'
    '            if isinstance(e, dict)\n'
    '            and e.get("symbol") == symbol\n'
    '            and e.get("outcome") is None\n'
    '        ),\n'
    '        None,\n'
    '    )'
)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def abort(msg: str) -> None:
    print(f"\nABORT — {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("fix_journal_reader.py — patch _do_record_outcome() for dict-of-dates format")
    print("=" * 74)

    if not TARGET.exists():
        abort(f"Target not found: {TARGET}")

    src = TARGET.read_text(encoding="utf-8")

    if OLD not in src:
        if 'entries_iter' in src:
            print("  Already applied — nothing to do.")
            return
        abort(
            "Anchor text not found — file may differ from expected state.\n"
            "Restore from backup and re-run upgrade_layer2.py, then this script."
        )

    print(f"  Before SHA-256: {sha256_of(TARGET)}")
    patched = src.replace(OLD, NEW, 1)

    tmp = TARGET.with_suffix(".fixjr_tmp")
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
    print("PATCH: PASS — _do_record_outcome() now handles dict-of-dates journal")
    print()
    print("Test:")
    print(f"  python3 {TARGET} --record-outcome BTCUSDT void")
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
