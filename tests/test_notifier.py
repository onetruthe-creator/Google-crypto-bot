import json
from pathlib import Path
import pytest
from ladybug.notifier import send_alert, send_withdrawal
from ladybug.state import Phase, SymbolState


def _state() -> SymbolState:
    s = SymbolState(symbol="BTCUSDT")
    s.phase = Phase.REJECTION
    s.level = 50000.0
    return s


def test_send_alert_writes_file(tmp_path):
    out = tmp_path / "alerts.jsonl"
    state = _state()
    send_alert("BTCUSDT", state, str(out))
    assert out.exists()
    line = json.loads(out.read_text().strip())
    assert line["authorization"] == "NONE"
    assert line["event"] == "CONFIRMED_ANALYSIS"
    assert line["symbol"] == "BTCUSDT"
    assert line["level"] == pytest.approx(50000.0)


def test_send_withdrawal_writes_file(tmp_path):
    out = tmp_path / "alerts.jsonl"
    state = _state()
    send_withdrawal("BTCUSDT", state, str(out), reason="test invalidation")
    line = json.loads(out.read_text().strip())
    assert line["event"] == "WITHDRAWAL"
    assert line["reason"] == "test invalidation"
    assert line["authorization"] == "NONE"


def test_send_alert_appends(tmp_path):
    out = tmp_path / "alerts.jsonl"
    state = _state()
    send_alert("BTCUSDT", state, str(out))
    send_alert("ETHUSDT", state, str(out))
    lines = [l for l in out.read_text().strip().splitlines() if l]
    assert len(lines) == 2


def test_authorization_none_in_message(tmp_path):
    out = tmp_path / "alerts.jsonl"
    state = _state()
    send_alert("BTCUSDT", state, str(out))
    line = json.loads(out.read_text().strip())
    assert "NONE" in line["message"]
