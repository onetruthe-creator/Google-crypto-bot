from __future__ import annotations
import time
import requests
from typing import Any


class BitunixError(RuntimeError):
    pass


class BitunixClient:
    BASE_URL = "https://fapi.bitunix.com"

    def __init__(self, base_url: str = BASE_URL, timeout: int = 10) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        self._session.headers["Content-Type"] = "application/json"

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise BitunixError(f"HTTP error on {url}: {exc}") from exc
        data = resp.json()
        if isinstance(data, dict):
            code = data.get("code")
            if code is not None and str(code) not in ("0", "200"):
                raise BitunixError(f"Bitunix API error {code}: {data.get('msg', data)}")
            inner = data.get("data")
            return inner if inner is not None else data
        return data

    def get_tickers(self, symbols: list[str] | None = None) -> list[dict]:
        params = {}
        if symbols:
            params["symbols"] = ",".join(symbols)
        result = self._get("/api/v1/futures/market/tickers", params or None)
        if isinstance(result, list):
            return result
        return []

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list:
        # API uses startTime/endTime in milliseconds; derive startTime from limit
        interval_ms = _interval_to_ms(interval)
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - interval_ms * limit
        result = self._get("/api/v1/futures/market/kline", {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
        })
        if isinstance(result, list):
            return result
        return []


def _interval_to_ms(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    for suffix, ms in units.items():
        if interval.endswith(suffix):
            try:
                return int(interval[:-1]) * ms
            except ValueError:
                pass
    return 3_600_000  # default 1h
