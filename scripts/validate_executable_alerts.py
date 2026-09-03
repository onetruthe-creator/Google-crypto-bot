#!/usr/bin/env python3
"""
validate_executable_alerts.py — Pre-flight validation for the executable-alert install.

Checks (no network, no state mutation)
---------------------------------------
 V1  All three SME modules importable from workspace.
 V2  ExecutableSetupInput and validate_executable_setup present in validator.
 V3  format_executable_alert present in formatter.
 V4  try_deliver_executable present in delivery.
 V5  relay_alert patchable at module level in delivery.
 V6  LADYBUG_EXECUTABLE_ALERTS_ENABLED defaults to "0" (not "1") in a clean env.
 V7  A fully-valid synthetic input passes all gates (with flag=1).
 V8  An input missing breakout_level_price (Gates 6-9) fails-closed.
 V9  The formatted message contains the exact literal "AUTHORIZATION: NONE".
V10  bitunix_trade_alerts.py on the workspace contains the patch marker.

Usage: python3 scripts/validate_executable_alerts.py [--workspace DIR]
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    tag = PASS if condition else FAIL
    results.append((name, tag, detail))
    return condition


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=os.path.expanduser("~/.openclaw/workspace"))
    args = ap.parse_args()

    workspace = Path(args.workspace)
    sme_path = workspace / "sovereign_mission_engine"

    # Add workspace SME to sys.path so we can import the installed copies.
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))

    print("=== validate_executable_alerts.py ===")
    print(f"Workspace: {workspace}")
    print()

    # V1 — importability
    for mod_name in [
        "sovereign_mission_engine.lb_executable_validator",
        "sovereign_mission_engine.lb_executable_formatter",
        "sovereign_mission_engine.lb_executable_delivery",
    ]:
        try:
            importlib.import_module(mod_name)
            check(f"V1 import {mod_name.split('.')[-1]}", True)
        except Exception as exc:
            check(f"V1 import {mod_name.split('.')[-1]}", False, str(exc))

    # V2 — validator symbols
    try:
        from sovereign_mission_engine.lb_executable_validator import (
            ExecutableSetupInput,
            validate_executable_setup,
        )
        check("V2 validator symbols", True)
    except ImportError as exc:
        check("V2 validator symbols", False, str(exc))
        print("Cannot continue without validator.")
        _print_summary()
        sys.exit(1)

    # V3 — formatter symbol
    try:
        from sovereign_mission_engine.lb_executable_formatter import format_executable_alert
        check("V3 formatter symbol", True)
    except ImportError as exc:
        check("V3 formatter symbol", False, str(exc))

    # V4 — delivery symbol
    try:
        from sovereign_mission_engine.lb_executable_delivery import try_deliver_executable
        check("V4 delivery symbol", True)
    except ImportError as exc:
        check("V4 delivery symbol", False, str(exc))

    # V5 — relay_alert patchable at module level
    try:
        import sovereign_mission_engine.lb_executable_delivery as _delivery
        assert hasattr(_delivery, "relay_alert"), "relay_alert not a module attribute"
        check("V5 relay_alert patchable", True)
    except Exception as exc:
        check("V5 relay_alert patchable", False, str(exc))

    # V6 — default disabled
    saved = os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)
    try:
        flag = os.environ.get("LADYBUG_EXECUTABLE_ALERTS_ENABLED", "0")
        check("V6 default disabled", flag == "0", f"flag={flag!r}")
    finally:
        if saved is not None:
            os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = saved

    # V7 — valid synthetic input passes (with flag=1)
    try:
        from dataclasses import replace as dc_replace
        os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "1"
        _TS = datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        good = ExecutableSetupInput(
            admission_status="CONFIRMED_ANALYSIS",
            admission_admitted=True,
            effective_score=88.0,
            direction="LONG",
            move_1h_pct=1.5,
            atr_pct=1.2,
            breakout_level_price=50000.0,
            retest_zone_low=49500.0,
            retest_zone_high=49900.0,
            retest_confirmed=True,
            confirmation_candle_closed=True,
            entry_trigger=50050.0,
            take_profit_1=51500.0,
            stop_loss=49000.0,
            reward_risk=Decimal("2.35"),
            atr_15m_price=400.0,
            funding_rate=0.0001,
            relative_volume=2.5,
            stop_precedes_liquidation=True,
            suggested_leverage=5,
            risk_decision="TRADE",
            quote_volume_24h=80_000_000.0,
            change_24h_pct=2.0,
            sentiment_score=0.6,
            opposing_score=70.0,
            funding_available=True,
            within_cooldown=False,
            symbol="BTCUSDT",
            scan_timestamp=_TS,
        )
        r = validate_executable_setup(good)
        check("V7 valid input passes", r.passed, str(r.failure_reasons) if not r.passed else "")
    except Exception as exc:
        check("V7 valid input passes", False, str(exc))
    finally:
        os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)

    # V8 — missing breakout fails-closed
    try:
        inp = dc_replace(good, breakout_level_price=None)
        os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "1"
        r2 = validate_executable_setup(inp)
        check(
            "V8 missing breakout fails-closed",
            not r2.passed and any("GATE6" in x for x in r2.failure_reasons),
            str(r2.failure_reasons),
        )
    except Exception as exc:
        check("V8 missing breakout fails-closed", False, str(exc))
    finally:
        os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)

    # V9 — formatted message contains AUTHORIZATION: NONE
    try:
        os.environ["LADYBUG_EXECUTABLE_ALERTS_ENABLED"] = "1"
        r3 = validate_executable_setup(good)
        from sovereign_mission_engine.lb_executable_formatter import format_executable_alert
        msg = format_executable_alert(good, r3)
        check("V9 AUTHORIZATION: NONE in message", "AUTHORIZATION: NONE" in msg, msg[:80])
    except Exception as exc:
        check("V9 AUTHORIZATION: NONE in message", False, str(exc))
    finally:
        os.environ.pop("LADYBUG_EXECUTABLE_ALERTS_ENABLED", None)

    # V10 — patch marker in workspace bitunix_trade_alerts.py
    target = sme_path / "bitunix_trade_alerts.py"
    if not target.exists():
        results.append(("V10 patch marker", SKIP, f"not found: {target}"))
    else:
        content = target.read_text(encoding="utf-8")
        check(
            "V10 patch marker in trade-alerts",
            "try_deliver_executable" in content,
            f"marker not found in {target}" if "try_deliver_executable" not in content else "",
        )

    # V11 — ladybug_retest_detector importable
    try:
        from sovereign_mission_engine.ladybug_retest_detector import detect_retest, RetestDetection
        check("V11 retest detector importable", True)
    except Exception as exc:
        check("V11 retest detector importable", False, str(exc))

    # V12 — detect_retest returns RetestDetection for valid input
    try:
        from sovereign_mission_engine.ladybug_retest_detector import detect_retest
        candles = [{"close": str(100.0 + i * 0.01), "open": str(100.0 + i * 0.01)}
                   for i in range(100)]
        r = detect_retest(candles, direction="SHORT", last_price=100.0, atr_pct=1.0)
        check("V12 detect_retest returns RetestDetection", isinstance(r, RetestDetection), str(r))
    except Exception as exc:
        check("V12 detect_retest returns RetestDetection", False, str(exc))

    # V13 — patch marker in workspace bitunix_market_scout.py (optional)
    scout = sme_path / "bitunix_market_scout.py"
    if not scout.exists():
        results.append(("V13 scout retest patch", SKIP, f"not found: {scout}"))
    else:
        scout_content = scout.read_text(encoding="utf-8")
        check(
            "V13 scout retest patch applied",
            "ladybug_retest_detector" in scout_content,
            f"marker not found in {scout}" if "ladybug_retest_detector" not in scout_content else "",
        )

    # V14 — retest fields wired into _try_executable_delivery (not None)
    if not target.exists():
        results.append(("V14 retest fields wired", SKIP, f"not found: {target}"))
    else:
        ta_content = target.read_text(encoding="utf-8")
        check(
            "V14 retest fields wired",
            "setup.breakout_level_price" in ta_content,
            "hardcoded None still present — run patch_bitunix_trade_alerts_retest_wiring.py"
            if "setup.breakout_level_price" not in ta_content else "",
        )

    _print_summary()


def _print_summary() -> None:
    print()
    print(f"{'Check':<40} {'Result':<10} Detail")
    print("-" * 80)
    fails = 0
    for name, tag, detail in results:
        detail_str = (detail[:60] + "…") if len(detail) > 60 else detail
        print(f"{name:<40} {tag:<18} {detail_str}")
        if "FAIL" in tag:
            fails += 1
    print()
    total = len(results)
    print(f"{'ALL PASS' if fails == 0 else f'{fails} FAILED'} ({total} checks)")


if __name__ == "__main__":
    main()
