from __future__ import annotations
import yaml
from pathlib import Path
from typing import Any

_DEFAULT: dict = {
    "workspace": str(Path.home() / ".openclaw" / "workspace"),
    "bitunix": {
        "base_url": "https://fapi.bitunix.com",
        "watchlist_size": 20,
        "timeout_seconds": 10,
    },
    "detector": {
        "kline_interval": "1h",
        "kline_limit": 100,
        "swing_lookback": 5,
        "breakout_volume_multiplier": 1.5,
        "retest_tolerance_pct": 0.5,
        "rejection_min_move_pct": 0.3,
    },
    "gates": {
        "rsi_period": 14,
        "rsi_max": 75,
        "min_volume_usdt": 1_000_000,
    },
    "notifier": {
        "output_file": "",
        "webhook_url": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    def __init__(self, path: str | Path | None = None) -> None:
        cfg = _deep_merge({}, _DEFAULT)
        if path and Path(path).exists():
            with open(path) as f:
                user = yaml.safe_load(f) or {}
            cfg = _deep_merge(cfg, user)
        self._cfg = cfg
        ws = self.workspace
        if not self._cfg["notifier"]["output_file"]:
            self._cfg["notifier"]["output_file"] = str(ws / "ladybug_alerts.jsonl")

    def __getitem__(self, key: str) -> Any:
        return self._cfg[key]

    @property
    def workspace(self) -> Path:
        return Path(self._cfg["workspace"])

    @property
    def state_file(self) -> Path:
        return self.workspace / "ladybug_state.json"

    @property
    def watchlist_file(self) -> Path:
        return self.workspace / "ladybug_watchlist.json"

    @property
    def config_file(self) -> Path:
        return self.workspace / "ladybug_config.yaml"
