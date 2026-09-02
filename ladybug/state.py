from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Phase(str, Enum):
    NONE = "none"
    BREAKOUT = "breakout"
    RETEST = "retest"
    REJECTION = "rejection"
    PENDING = "pending"       # gates passed once; awaiting second consecutive pass
    CONFIRMED = "confirmed"   # alert sent
    WITHDRAWN = "withdrawn"   # setup became invalid; withdrawal sent


@dataclass
class SymbolState:
    symbol: str
    phase: Phase = Phase.NONE
    level: float = 0.0
    breakout_ts: Optional[int] = None
    retest_ts: Optional[int] = None
    rejection_ts: Optional[int] = None
    pending_ts: Optional[int] = None
    alert_sent: bool = False
    withdrawal_sent: bool = False


def _state_from_dict(d: dict) -> SymbolState:
    d = dict(d)
    d["phase"] = Phase(d.get("phase", Phase.NONE))
    return SymbolState(**{k: v for k, v in d.items() if k in SymbolState.__dataclass_fields__})


class StateManager:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._states: dict[str, SymbolState] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                raw = json.load(f)
            for sym, data in raw.items():
                self._states[sym] = _state_from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            self._states = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw: dict[str, dict] = {}
        for sym, s in self._states.items():
            d = asdict(s)
            d["phase"] = s.phase.value
            raw[sym] = d
        with open(self._path, "w") as f:
            json.dump(raw, f, indent=2)

    def get(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol=symbol)
        return self._states[symbol]

    def set(self, state: SymbolState) -> None:
        self._states[state.symbol] = state

    def reset(self, symbol: str) -> None:
        self._states[symbol] = SymbolState(symbol=symbol)
