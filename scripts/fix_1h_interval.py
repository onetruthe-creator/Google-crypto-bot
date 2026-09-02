#!/usr/bin/env python3
"""
fix_1h_interval.py — change "1H" → "1h" in crypto-signals.py

Bitunix kline API is case-sensitive: "1H" returns 0 candles (silently);
"1h" returns 100.  This patch corrects the four places upgrade_layer2.py
inserted "1H" (INTERVALS, TF_W, TF_LIM, TE keys).

AUTHORIZATION: NONE — read-only analysis fix; no orders placed.
"""
from __future__ import annotations
import hashlib, os, subprocess, sys
from pathlib import Path

TARGET = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"

# Each (old, new) pair is a verbatim string replacement, applied once.
SWAPS = [
    (
        'INTERVALS=["4H","1H","30m","15m","3m"]',
        'INTERVALS=["4H","1h","30m","15m","3m"]',
    ),
    (
        'TF_W={"4H":4,"1H":3,"30m":3,"15m":2,"3m":1}',
        'TF_W={"4H":4,"1h":3,"30m":3,"15m":2,"3m":1}',
    ),
    (
        'TF_LIM={"4H":100,"1H":100,"30m":100,"15m":100,"3m":60}',
        'TF_LIM={"4H":100,"1h":100,"30m":100,"15m":100,"3m":60}',
    ),
    # TE key — the emoji value stays the same, only the key changes.
    # The Unicode literal \U0001f551 = 🕑
    ('"1H":"\U0001f551"', '"1h":"\U0001f551"'),
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def abort(msg: str) -> None:
    print(f"\nABORT — {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("fix_1h_interval.py — change \"1H\" → \"1h\" in crypto-signals.py")
    print("=" * 62)

    if not TARGET.exists():
        abort(f"Target not found: {TARGET}")

    src = TARGET.read_text(encoding="utf-8")

    # Quick idempotency check
    if '"1h":' in src and '"1H":' not in src and '"1H",' not in src:
        print("  Already applied — nothing to do.")
        return

    print(f"  Before SHA-256: {sha256_of(TARGET)}")

    applied = []
    for old, new in SWAPS:
        if old in src:
            src = src.replace(old, new, 1)
            applied.append(f"  ✓  {old[:50]!r}")
        elif new in src:
            applied.append(f"  ↩  already: {new[:50]!r}")
        else:
            abort(
                f"Anchor not found:\n  {old!r}\n"
                "File may differ from expected post-upgrade state.\n"
                "Restore from backup and re-run upgrade_layer2.py, then this script."
            )

    tmp = TARGET.with_suffix(".fix1h_tmp")
    try:
        tmp.write_text(src, encoding="utf-8")
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

    for line in applied:
        print(line)
    print()
    print(f"  After  SHA-256: {sha256_of(TARGET)}")
    print()
    print('PATCH: PASS — 1H → 1h applied; re-run --scan to confirm 1h rows show data')
    print()
    print("AUTHORIZATION: NONE")


if __name__ == "__main__":
    main()
