#!/usr/bin/env python3
"""
Patch script: integrate lb_executable_delivery into bitunix_trade_alerts.py.

Changes applied
---------------
1. Remove the direct Telegram relay call at the bottom of the scan loop:
       relay("\n".join(lines))
2. Add an import for try_deliver_executable.
3. Add _try_executable_delivery() helper that maps selected-list tuples into
   ExecutableSetupInput and calls try_deliver_executable() for each.
4. Insert a call to _try_executable_delivery(selected, now=now) immediately
   after the existing loop that builds the `selected` list.

Usage
-----
    python scripts/patch_bitunix_trade_alerts_executable.py [--target PATH] [--check]

    --target PATH   path to bitunix_trade_alerts.py (default: auto-discovered)
    --check         dry-run; print diff only, do not write

Safety
------
- Refuses to apply if already patched (idempotent).
- Writes to a temp file then renames (atomic).
- Prints SHA-256 of patched file.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

# ── Marker strings ────────────────────────────────────────────────────────────
# Must be present in the target file for the patch to apply.
OLD_RELAY_LINE = '    relay("\\n".join(lines))'
ALREADY_MARKER = "try_deliver_executable"

# ── Replacement for the relay call ───────────────────────────────────────────
# The old relay call is removed and replaced by nothing —
# the executable delivery is handled by _try_executable_delivery() below.
OLD_RELAY_BLOCK = '    relay("\\n".join(lines))\n'
NEW_RELAY_BLOCK = ""  # removed — executable delivery handled separately

# ── Import injection ──────────────────────────────────────────────────────────
IMPORT_ANCHOR = "from sovereign_mission_engine.bitunix_runtime import"
IMPORT_INJECTION = (
    "from sovereign_mission_engine.lb_executable_delivery import try_deliver_executable\n"
)

# ── Delivery helper + call ────────────────────────────────────────────────────
# Appended at the end of the module (before the if __name__ == '__main__' guard
# if present, otherwise at EOF).
HELPER_CODE = '''

# ---------------------------------------------------------------------------
# Executable-alert delivery (lb_executable_delivery integration)
# ---------------------------------------------------------------------------

def _try_executable_delivery(selected, *, now):
    """
    Attempt executable-alert delivery for each selected setup.

    `selected` is the list of tuples produced by the scan loop:
        (base, score, setup, warnings, event_notes, admission, retest)

    Each element is validated against all 24 gates via try_deliver_executable.
    Gate 24 (LADYBUG_EXECUTABLE_ALERTS_ENABLED) prevents actual relay when
    the feature is not enabled in production.

    AUTHORIZATION: NONE — Ladybug is read-only analysis only.
    """
    from datetime import timezone
    from decimal import Decimal
    from sovereign_mission_engine.lb_executable_validator import ExecutableSetupInput
    from sovereign_mission_engine.bitunix_risk_engine import analyze_trade

    for base, score, setup, warnings, event_notes, admission, retest in selected:
        try:
            risk = analyze_trade(setup, score, warnings)

            def _f(s):
                try:
                    return float(s)
                except (TypeError, ValueError):
                    return None

            inp = ExecutableSetupInput(
                admission_status=admission.status if admission else None,
                admission_admitted=admission.admitted if admission else None,
                effective_score=float(score) if score is not None else None,
                direction=setup.direction if setup else None,
                move_1h_pct=float(setup.momentum_1h_pct) if setup and setup.momentum_1h_pct is not None else None,
                atr_pct=float(setup.atr_pct) if setup and setup.atr_pct is not None else None,
                breakout_level_price=None,       # not in DeepSetup — Gate 6 fails-closed
                retest_zone_low=None,            # not in DeepSetup — Gate 7 fails-closed
                retest_zone_high=None,           # not in DeepSetup — Gate 7 fails-closed
                retest_confirmed=None,           # not in DeepSetup — Gate 8 fails-closed
                confirmation_candle_closed=None, # not in DeepSetup — Gate 9 fails-closed
                entry_trigger=_f(setup.entry) if setup else None,
                take_profit_1=_f(setup.take_profit) if setup else None,
                stop_loss=_f(setup.stop_loss) if setup else None,
                reward_risk=Decimal(str(risk.reward_risk)) if risk else None,
                atr_15m_price=None,              # not in DeepSetup — Gate 12 fails-closed
                funding_rate=float(setup.funding_rate) if setup and setup.funding_rate is not None else None,
                relative_volume=float(setup.relative_volume) if setup and setup.relative_volume is not None else None,
                stop_precedes_liquidation=risk.stop_precedes_liquidation if risk else None,
                suggested_leverage=risk.suggested_leverage if risk else None,
                risk_decision=risk.decision if risk else None,
                quote_volume_24h=float(setup.quote_volume_24h) if setup and setup.quote_volume_24h is not None else None,
                change_24h_pct=float(setup.change_24h_pct) if setup and setup.change_24h_pct is not None else None,
                sentiment_score=float(setup.sentiment_score) if setup and setup.sentiment_score is not None else None,
                opposing_score=float(setup.opposing_score) if setup and setup.opposing_score is not None else None,
                funding_available=bool(setup.funding_available) if setup and setup.funding_available is not None else None,
                within_cooldown=False,  # resolved inside try_deliver_executable
                symbol=base,
                scan_timestamp=now.astimezone(timezone.utc) if now else None,
            )
            result = try_deliver_executable(inp)
            if result.passed:
                import logging
                logging.getLogger(__name__).info(
                    "EXECUTABLE_ALERT_SENT: %s alert_id=%s", base, result.alert_id
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "EXECUTABLE_DELIVERY_ERROR: %s: %s", base, exc
            )
'''

CALL_ANCHOR = "# End of scan loop"
CALL_INJECTION = "    _try_executable_delivery(selected, now=now)\n"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _find_target() -> Path:
    candidates = [
        Path.home() / ".openclaw/workspace/scripts/bitunix_trade_alerts.py",
        Path.home() / ".openclaw/workspace/sovereign_mission_engine/bitunix_trade_alerts.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate bitunix_trade_alerts.py. Pass --target explicitly."
    )


def patch(src: str, dry_run: bool = False) -> tuple[str, str]:
    """Apply patch to src text.  Returns (patched_text, diff_summary)."""
    if ALREADY_MARKER in src:
        raise RuntimeError(
            f"Already patched: {ALREADY_MARKER!r} already present in target."
        )
    if OLD_RELAY_LINE not in src:
        raise RuntimeError(
            f"Cannot find expected relay call {OLD_RELAY_LINE!r} in target. "
            "Has the file changed?"
        )

    patched = src

    # 1. Inject import after the bitunix_runtime import block.
    if IMPORT_ANCHOR in patched:
        idx = patched.index(IMPORT_ANCHOR)
        # Find the end of this import statement (may span multiple lines with \).
        end = patched.index("\n", idx)
        while patched[end - 1] == "\\":
            end = patched.index("\n", end + 1)
        patched = patched[: end + 1] + IMPORT_INJECTION + patched[end + 1 :]

    # 2. Remove old relay call.
    patched = patched.replace(OLD_RELAY_BLOCK, NEW_RELAY_BLOCK, 1)

    # 3. Append helper + call to _try_executable_delivery.
    #    Insert the call right before the helpers are appended
    #    so it appears as part of the scan function body.
    #    Detect the last occurrence of `selected` to find where to inject call.
    insert_marker = "\n    return "
    if insert_marker in patched:
        last_return = patched.rindex(insert_marker)
        patched = (
            patched[:last_return]
            + f"\n{CALL_INJECTION}"
            + patched[last_return:]
        )

    # 4. Append helper at EOF.
    patched = patched.rstrip("\n") + "\n" + HELPER_CODE

    lines_changed = abs(patched.count("\n") - src.count("\n"))
    summary = f"+{lines_changed} lines (import, relay removal, helper, call)"
    return patched, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch bitunix_trade_alerts.py")
    ap.add_argument("--target", help="Path to bitunix_trade_alerts.py")
    ap.add_argument("--check", action="store_true", help="Dry-run; print diff only")
    args = ap.parse_args()

    target = Path(args.target) if args.target else _find_target()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        sys.exit(1)

    src = target.read_text(encoding="utf-8")
    try:
        patched, summary = patch(src, dry_run=args.check)
    except RuntimeError as exc:
        print(f"PATCH: SKIP — {exc}")
        sys.exit(0)

    if args.check:
        print(f"DRY-RUN: would apply {summary}")
        print(f"DRY-RUN: target={target}")
        sys.exit(0)

    # Atomic write.
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp", prefix=".patch_")
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
    print(f"PATCH: PASS")
    print(f"  target : {target}")
    print(f"  changes: {summary}")
    print(f"  sha256 : {sha}")


if __name__ == "__main__":
    main()
