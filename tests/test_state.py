import json
import tempfile
from pathlib import Path
import pytest
from ladybug.state import Phase, SymbolState, StateManager


def test_phase_values():
    assert Phase.NONE.value == "none"
    assert Phase.CONFIRMED.value == "confirmed"


def test_symbol_state_defaults():
    s = SymbolState(symbol="BTCUSDT")
    assert s.phase == Phase.NONE
    assert s.level == 0.0
    assert not s.alert_sent


def test_state_manager_persist(tmp_path):
    path = tmp_path / "state.json"
    mgr = StateManager(path)
    s = mgr.get("ETHUSDT")
    s.phase = Phase.BREAKOUT
    s.level = 2500.0
    mgr.set(s)
    mgr.save()

    mgr2 = StateManager(path)
    s2 = mgr2.get("ETHUSDT")
    assert s2.phase == Phase.BREAKOUT
    assert s2.level == pytest.approx(2500.0)


def test_state_manager_reset(tmp_path):
    path = tmp_path / "state.json"
    mgr = StateManager(path)
    s = mgr.get("XRPUSDT")
    s.phase = Phase.PENDING
    mgr.set(s)
    mgr.reset("XRPUSDT")
    assert mgr.get("XRPUSDT").phase == Phase.NONE


def test_state_manager_missing_file(tmp_path):
    mgr = StateManager(tmp_path / "nonexistent.json")
    s = mgr.get("SOLUSDT")
    assert s.phase == Phase.NONE


def test_state_manager_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    mgr = StateManager(path)
    assert mgr.get("BTCUSDT").phase == Phase.NONE
