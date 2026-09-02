import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from ladybug.watchlist import build_watchlist, save_watchlist, load_watchlist, _vol, _sym


def _ticker(symbol: str, vol: float) -> dict:
    return {"symbol": symbol, "quoteVolume": str(vol)}


def test_vol_parsing():
    assert _vol({"quoteVolume": "1000000.5"}) == pytest.approx(1_000_000.5)
    assert _vol({"vol": "500"}) == pytest.approx(500.0)
    assert _vol({}) == 0.0


def test_sym_parsing():
    assert _sym({"symbol": "BTCUSDT"}) == "BTCUSDT"
    assert _sym({"instId": "ETHUSDT"}) == "ETHUSDT"
    assert _sym({}) == ""


def test_build_watchlist_filters_and_sorts():
    cfg = MagicMock()
    cfg.__getitem__ = lambda self, k: {
        "gates": {"min_volume_usdt": 1_000_000},
        "bitunix": {"watchlist_size": 3},
    }[k]
    client = MagicMock()
    client.get_tickers.return_value = [
        _ticker("BTCUSDT", 5_000_000),
        _ticker("ETHUSDT", 3_000_000),
        _ticker("XRPUSDT", 800_000),   # below min_vol
        _ticker("SOLUSDT", 2_000_000),
        _ticker("BTCBTC", 9_000_000),  # not USDT
    ]
    symbols = build_watchlist(client, cfg)
    assert symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_save_and_load_watchlist(tmp_path):
    path = tmp_path / "wl.json"
    syms = ["BTCUSDT", "ETHUSDT"]
    save_watchlist(syms, path)
    loaded = load_watchlist(path)
    assert loaded == syms


def test_load_watchlist_missing(tmp_path):
    assert load_watchlist(tmp_path / "nope.json") == []


def test_load_watchlist_corrupt(tmp_path):
    path = tmp_path / "wl.json"
    path.write_text("not json")
    assert load_watchlist(path) == []
