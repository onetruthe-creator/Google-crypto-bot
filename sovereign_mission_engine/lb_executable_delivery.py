"""
Ladybug Executable-Alert Delivery Layer.

Responsibilities
----------------
1. Maintain a dedup store (state file) keyed by alert_id with expiry.
2. Check Gate 23 (cooldown) before calling the validator.
3. Call the formatter and relay only when all 24 gates pass.
4. Never raise on relay failure — log and continue.

AUTHORIZATION: NONE — this system is read-only analysis only.
Production delivery is gated by LADYBUG_EXECUTABLE_ALERTS_ENABLED=1.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sovereign_mission_engine.lb_executable_formatter import format_executable_alert
from sovereign_mission_engine.lb_executable_validator import (
    ExecutableSetupInput,
    ExecutableValidatorResult,
    validate_executable_setup,
)

try:
    from sovereign_mission_engine.bitunix_runtime import (
        load_json_state as _rt_load_json_state,
        relay_alert as _rt_relay_alert,
        save_json_state as _rt_save_json_state,
    )
    _RUNTIME_AVAILABLE = True
except ImportError:
    _rt_load_json_state = None  # type: ignore[assignment]
    _rt_relay_alert = None      # type: ignore[assignment]
    _rt_save_json_state = None  # type: ignore[assignment]
    _RUNTIME_AVAILABLE = False


def relay_alert(message: str, *, relay_url: str, **kwargs: Any) -> None:
    """Thin wrapper so tests can patch at module level."""
    if _rt_relay_alert is None:
        raise RuntimeError("bitunix_runtime not available")
    _rt_relay_alert(message, relay_url=relay_url, **kwargs)


def load_json_state(filename: str, *, default_factory: Any, **kwargs: Any) -> dict:
    if _rt_load_json_state is None:
        return default_factory()
    return _rt_load_json_state(filename, default_factory=default_factory, **kwargs)


def save_json_state(filename: str, state: Any, **kwargs: Any) -> None:
    if _rt_save_json_state is None:
        return
    _rt_save_json_state(filename, state, **kwargs)

log = logging.getLogger(__name__)

_STATE_FILE = "lb-executable-alerts.json"
_RELAY_URL = "http://127.0.0.1:8099/relay_lb"
_COOLDOWN_SECONDS = 14_400          # 4 hours between identical alert_ids
_PURGE_AFTER_SECONDS = 86_400       # remove entries older than 24 h from state


def _now_ts() -> float:
    return time.time()


def _load_state() -> dict[str, Any]:
    try:
        return load_json_state(_STATE_FILE, default_factory=lambda: {"sent": {}})
    except Exception as exc:
        log.warning("lb_executable_delivery: could not load state: %s", exc)
        return {"sent": {}}


def _save_state(state: dict[str, Any]) -> None:
    try:
        save_json_state(_STATE_FILE, state)
    except Exception as exc:
        log.warning("lb_executable_delivery: could not save state: %s", exc)


def _purge_old(sent: dict[str, Any]) -> dict[str, Any]:
    cutoff = _now_ts() - _PURGE_AFTER_SECONDS
    return {k: v for k, v in sent.items() if v.get("ts", 0) >= cutoff}


def _within_cooldown(sent: dict[str, Any], alert_id: str) -> bool:
    entry = sent.get(alert_id)
    if entry is None:
        return False
    return _now_ts() - entry.get("ts", 0) < _COOLDOWN_SECONDS


def try_deliver_executable(inp: ExecutableSetupInput) -> ExecutableValidatorResult:
    """
    Validate inp against all 24 gates; if passed, format and relay.

    Returns the ExecutableValidatorResult regardless of delivery outcome.
    Gate 23 (cooldown) is resolved here using the live state file before
    the validator is called.
    """
    state = _load_state()
    sent: dict[str, Any] = state.get("sent", {})
    sent = _purge_old(sent)

    # Pre-compute a provisional alert_id to check cooldown (Gate 23).
    # The validator re-derives the same id deterministically.
    provisional_id = ""
    if (
        inp.symbol
        and inp.direction
        and inp.entry_trigger is not None
        and inp.stop_loss is not None
        and inp.take_profit_1 is not None
        and inp.scan_timestamp is not None
    ):
        from sovereign_mission_engine.lb_executable_validator import compute_alert_id
        try:
            provisional_id = compute_alert_id(
                symbol=inp.symbol,
                direction=inp.direction,
                entry_trigger=inp.entry_trigger,
                stop_loss=inp.stop_loss,
                take_profit_1=inp.take_profit_1,
                scan_timestamp=inp.scan_timestamp,
            )
        except Exception:
            provisional_id = ""

    within_cd = _within_cooldown(sent, provisional_id) if provisional_id else False

    # Rebuild inp with Gate 23 resolved so the validator sees it.
    import dataclasses as _dc
    inp_with_cd = ExecutableSetupInput(
        **{f.name: getattr(inp, f.name) for f in _dc.fields(inp)
           if f.name != "within_cooldown"},
        within_cooldown=within_cd,
    )

    result = validate_executable_setup(inp_with_cd)
    log.info(
        "lb_executable_delivery: alert_id=%s passed=%s gates_failed=%d",
        result.alert_id,
        result.passed,
        len(result.failure_reasons),
    )
    for reason in result.failure_reasons:
        log.debug("  %s", reason)

    if not result.passed:
        return result

    # All 24 gates passed — format and relay.
    try:
        message = format_executable_alert(
            inp_with_cd,
            result,
            suggested_leverage=inp_with_cd.suggested_leverage,
            reward_risk=inp_with_cd.reward_risk,
        )
    except Exception as exc:
        log.error("lb_executable_delivery: formatter error: %s", exc)
        return ExecutableValidatorResult(
            passed=False,
            alert_id=result.alert_id,
            failure_reasons=(f"FORMATTER_ERROR: {exc}",),
        )

    try:
        relay_alert(message, relay_url=_RELAY_URL)
        log.info("lb_executable_delivery: relayed alert_id=%s", result.alert_id)
    except Exception as exc:
        log.error("lb_executable_delivery: relay error: %s", exc)
        return ExecutableValidatorResult(
            passed=False,
            alert_id=result.alert_id,
            failure_reasons=(f"RELAY_ERROR: {exc}",),
        )

    # Record in dedup store.
    sent[result.alert_id] = {"ts": _now_ts(), "symbol": inp.symbol}
    state["sent"] = sent
    _save_state(state)

    return result
