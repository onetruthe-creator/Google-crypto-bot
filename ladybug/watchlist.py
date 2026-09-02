from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from .bitunix_client import BitunixClient
from .config import Config


def _vol(ticker: dict) -> float:
    for k in ("quoteVolume", "quote_volume", "volume24h", "vol24h", "vol", "volume"):
        v = ticker.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return 0.0


def _sym(ticker: dict) -> str:
    return str(ticker.get("symbol", ticker.get("instId", "")))


def build_watchlist(client: BitunixClient, cfg: Config) -> list[str]:
    tickers = client.get_tickers()
    min_vol = cfg["gates"]["min_volume_usdt"]
    size = cfg["bitunix"]["watchlist_size"]
    candidates = [(_sym(t), _vol(t)) for t in tickers if _sym(t).endswith("USDT")]
    filtered = [(sym, vol) for sym, vol in candidates if vol >= min_vol]
    filtered.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in filtered[:size]]


def save_watchlist(symbols: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "date": date.today().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "symbols": symbols,
        }, f, indent=2)


def load_watchlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f).get("symbols", [])
    except (json.JSONDecodeError, KeyError):
        return []
