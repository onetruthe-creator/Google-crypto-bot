from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from .bitunix_client import BitunixReadOnlyClient
from .config import Config


def build_watchlist(client: BitunixReadOnlyClient, cfg: Config) -> list[str]:
    min_vol = float(cfg["gates"]["min_volume_usdt"])
    size = cfg["bitunix"]["watchlist_size"]

    tickers = client.tickers()
    usdt_pairs = [t for t in tickers if t.symbol.endswith("USDT")]
    liquid = [t for t in usdt_pairs if float(t.quote_volume) >= min_vol]
    liquid.sort(key=lambda t: float(t.quote_volume), reverse=True)
    return [t.symbol for t in liquid[:size]]


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
