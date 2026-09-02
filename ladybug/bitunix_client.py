from __future__ import annotations
import threading
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests


class BitunixError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Layer-2 type: preserves Bitunix's original string values alongside
# validated Decimal fields.  Callers must use .raw for string preservation.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NormalizedTicker:
    symbol: str
    raw: dict                   # original strings from the API — Layer 2
    last_price: Decimal
    mark_price: Decimal
    open_price: Decimal         # 24-hour open (0 if unavailable)
    volume: Decimal             # base-asset volume
    quote_volume: Decimal       # quote (USDT) volume — used for liquidity screening
    price_change_pct: float     # 24h % change (0.0 when open unavailable)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_decimal(value: Any, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BitunixError(f"Cannot parse {field}={value!r} as Decimal") from exc
    if not d.is_finite():
        raise BitunixError(f"{field} is not a finite number: {value!r}")
    return d


def _validate_ticker(raw: dict) -> NormalizedTicker | None:
    sym = str(raw.get("symbol", raw.get("instId", ""))).strip()
    if not sym:
        return None

    try:
        last  = _to_decimal(raw.get("lastPrice") or raw.get("last") or 0, "lastPrice")
        mark  = _to_decimal(raw.get("markPrice") or raw.get("mark") or last, "markPrice")
        open_ = _to_decimal(raw.get("open24h") or raw.get("open") or raw.get("openPrice") or 0, "open")
        vol   = _to_decimal(raw.get("volume24h") or raw.get("vol") or raw.get("volume") or 0, "volume")
        qvol  = _to_decimal(raw.get("quoteVolume") or raw.get("quoteVol") or raw.get("turnover24h") or 0, "quoteVolume")
    except BitunixError:
        return None

    # finite positive prices
    if last <= 0 or mark <= 0:
        return None
    # nonnegative volume
    if vol < 0 or qvol < 0:
        return None
    # markPrice/lastPrice must agree within 1 %
    spread_pct = abs(float(mark - last)) / float(last) * 100
    if spread_pct > 1.0:
        return None

    # percentage movement: open > 0 guard required before division
    pct_change = 0.0
    if open_ > 0:
        pct_change = float((last - open_) / open_ * 100)

    return NormalizedTicker(
        symbol=sym,
        raw=raw,
        last_price=last,
        mark_price=mark,
        open_price=open_,
        volume=vol,
        quote_volume=qvol,
        price_change_pct=pct_change,
    )


class _TimedCache:
    """Thread-safe single-value cache with a TTL."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._value: Any = None
        self._ts: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> Any:
        with self._lock:
            if self._value is not None and time.monotonic() - self._ts < self._ttl:
                return self._value
        return None

    def set(self, value: Any) -> None:
        with self._lock:
            self._value = value
            self._ts = time.monotonic()


# ---------------------------------------------------------------------------
# Public client — read-only, no order placement
# ---------------------------------------------------------------------------

class BitunixReadOnlyClient:
    """
    Single authoritative Bitunix read-only client.
    Use tickers() for market discovery, liquidity screening, 24-hour
    movement, reference prices, and data-quality comparison.
    Do NOT use ticker snapshots for retest confirmation; use completed
    15-minute Klines and the stateful fixed-zone tracker instead.

    AUTHORIZATION: NONE
    """

    BASE_URL = "https://fapi.bitunix.com"

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 10,
        ticker_cache_ttl: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._ticker_cache: _TimedCache = _TimedCache(ticker_cache_ttl)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise BitunixError(f"HTTP error on {url}: {exc}") from exc

        data = resp.json()

        # Must be a JSON object
        if not isinstance(data, dict):
            raise BitunixError(f"Expected JSON object from {path}, got {type(data).__name__}")

        # code == 0 required
        code = data.get("code")
        if code is not None and str(code) not in ("0", "200"):
            raise BitunixError(f"Bitunix API error {code}: {data.get('msg', data)}")

        inner = data.get("data")
        if inner is None:
            raise BitunixError(f"Missing 'data' key in response from {path}")
        return inner

    # ------------------------------------------------------------------
    # Public API — tickers
    # ------------------------------------------------------------------

    def tickers(self, symbols: list[str] | None = None) -> list[NormalizedTicker]:
        """
        Return validated NormalizedTicker objects.
        Broad-market results are cached for ticker_cache_ttl seconds to stay
        comfortably below Bitunix's 10-requests-per-second-per-IP limit.
        """
        if not symbols:
            cached = self._ticker_cache.get()
            if cached is not None:
                return cached

        params: dict = {}
        if symbols:
            params["symbols"] = ",".join(symbols)

        raw_list = self._get("/api/v1/futures/market/tickers", params or None)
        if not isinstance(raw_list, list):
            raise BitunixError(f"Expected list under data, got {type(raw_list).__name__}")

        result = [t for raw in raw_list if (t := _validate_ticker(raw)) is not None]

        if not symbols:
            self._ticker_cache.set(result)
        return result

    # Thin alias so existing code that calls get_tickers() keeps working.
    # Returns raw dicts (Layer-2 string values preserved).
    def get_tickers(self) -> list[dict]:
        return [t.raw for t in self.tickers()]

    # ------------------------------------------------------------------
    # Public API — klines
    # ------------------------------------------------------------------

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> list:
        interval_ms = _interval_to_ms(interval)
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - interval_ms * limit
        inner = self._get("/api/v1/futures/market/kline", {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
        })
        return inner if isinstance(inner, list) else []


# Backward-compat alias
BitunixClient = BitunixReadOnlyClient


def _interval_to_ms(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    for suffix, ms in units.items():
        if interval.endswith(suffix):
            try:
                return int(interval[:-1]) * ms
            except ValueError:
                pass
    return 900_000  # default: 15 minutes
