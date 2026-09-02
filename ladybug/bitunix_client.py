from __future__ import annotations
import requests
from typing import Any


class BitunixError(RuntimeError):
    pass


class BitunixClient:
    def __init__(self, base_url: str = "https://fapi.bitunix.com", timeout: int = 10) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

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
            return data.get("data", data)
        return data

    def get_tickers(self) -> list[dict]:
        result = self._get("/api/v1/futures/ticker")
        if isinstance(result, list):
            return result
        return result if isinstance(result, list) else []

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list:
        result = self._get("/api/v1/futures/klines", {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })
        if isinstance(result, list):
            return result
        return []
