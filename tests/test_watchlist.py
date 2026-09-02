import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from ladybug.bitunix_client import NormalizedTicker, _validate_ticker
from ladybug.watchlist import build_watchlist, save_watchlist, load_watchlist


def _raw_ticker(symbol: str, quote_vol: float, last: float = 100.0) -> dict:
    return {
        "symbol": symbol,
        "lastPrice": str(last),
        "markPrice": str(last),
        "open24h": str(last * 0.98),
        "volume24h": str(quote_vol / last),
        "quoteVolume": str(quote_vol),
    }


def _ticker(symbol: str, quote_vol: float) -> NormalizedTicker:
    raw = _raw_ticker(symbol, quote_vol)
    t = _validate_ticker(raw)
    assert t is not None
    return t


def test_validate_ticker_valid():
    raw = _raw_ticker("BTCUSDT", 5_000_000, last=50000.0)
    t = _validate_ticker(raw)
    assert t is not None
    assert t.symbol == "BTCUSDT"
    assert t.last_price == pytest.approx(Decimal("50000.0"))
    assert t.quote_volume == pytest.approx(Decimal("5000000.0"))
    assert t.raw is raw  # original strings preserved


def test_validate_ticker_empty_symbol():
    assert _validate_ticker({"symbol": "", "lastPrice": "100", "markPrice": "100"}) is None


def test_validate_ticker_zero_price():
    assert _validate_ticker({"symbol": "BTCUSDT", "lastPrice": "0", "markPrice": "0"}) is None


def test_validate_ticker_mark_spread_too_wide():
    raw = {"symbol": "BTCUSDT", "lastPrice": "100", "markPrice": "102", "quoteVolume": "1000"}
    assert _validate_ticker(raw) is None


def test_validate_ticker_pct_change_no_open():
    raw = _raw_ticker("ETHUSDT", 1_000_000)
    raw.pop("open24h", None)
    t = _validate_ticker(raw)
    assert t is not None
    assert t.price_change_pct == 0.0


def test_build_watchlist_filters_and_sorts():
    cfg = MagicMock()
    cfg.__getitem__ = lambda self, k: {
        "gates": {"min_volume_usdt": 1_000_000},
        "bitunix": {"watchlist_size": 3},
    }[k]
    client = MagicMock()
    client.tickers.return_value = [
        _ticker("BTCUSDT",  5_000_000),
        _ticker("ETHUSDT",  3_000_000),
        _ticker("XRPUSDT",    800_000),   # below min_vol
        _ticker("SOLUSDT",  2_000_000),
        _ticker("BTCBTC",   9_000_000),   # not USDT pair
    ]
    symbols = build_watchlist(client, cfg)
    assert symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_save_and_load_watchlist(tmp_path):
    path = tmp_path / "wl.json"
    syms = ["BTCUSDT", "ETHUSDT"]
    save_watchlist(syms, path)
    assert load_watchlist(path) == syms


def test_load_watchlist_missing(tmp_path):
    assert load_watchlist(tmp_path / "nope.json") == []


def test_load_watchlist_corrupt(tmp_path):
    path = tmp_path / "wl.json"
    path.write_text("not json")
    assert load_watchlist(path) == []
