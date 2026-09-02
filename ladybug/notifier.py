from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional
import requests
from .state import SymbolState


_HEADER = "AUTHORIZATION: NONE"


def _build_payload(
    event: str,
    symbol: str,
    state: SymbolState,
    extra: Optional[dict] = None,
) -> dict:
    payload = {
        "authorization": "NONE",
        "event": event,
        "symbol": symbol,
        "level": state.level,
        "phase": state.phase.value,
        "timestamp": int(time.time() * 1000),
        "message": _HEADER,
    }
    if extra:
        payload.update(extra)
    return payload


def _write_alert(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(payload) + "\n")


def _post_webhook(url: str, payload: dict, timeout: int = 8) -> None:
    try:
        requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        pass


def send_alert(
    symbol: str,
    state: SymbolState,
    output_file: str,
    webhook_url: str = "",
    extra: Optional[dict] = None,
) -> None:
    payload = _build_payload("CONFIRMED_ANALYSIS", symbol, state, extra)
    _write_alert(Path(output_file), payload)
    if webhook_url:
        _post_webhook(webhook_url, payload)


def send_withdrawal(
    symbol: str,
    state: SymbolState,
    output_file: str,
    webhook_url: str = "",
    reason: str = "setup invalidated",
) -> None:
    payload = _build_payload("WITHDRAWAL", symbol, state, {"reason": reason})
    _write_alert(Path(output_file), payload)
    if webhook_url:
        _post_webhook(webhook_url, payload)
