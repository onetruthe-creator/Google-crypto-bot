#!/usr/bin/env python3
"""
TradingView → MaxMillion Adapter
=================================
Listens on port 8085 for TradingView webhook alerts, translates the payload
to MaxMillion format, and forwards it to http://localhost:8082/webhook.

TradingView sends:  {"ticker": "BTCUSDT", "action": "buy", "close": "50000"}
MaxMillion wants:   {"symbol": "BTC/USDT"}

Run:
    python3 tradingview_adapter.py

Then point your TradingView alert webhook at your ngrok URL, e.g.:
    https://abc123.ngrok-free.app/webhook
"""

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

# ── Config ─────────────────────────────────────────────────────────────────────
LISTEN_HOST    = "0.0.0.0"   # accept connections from anywhere
LISTEN_PORT    = 8085         # port TradingView (via ngrok) will hit
MAXMILLION_URL = "http://localhost:8082/webhook"

# Optional: set a secret token so only YOUR TradingView alerts are accepted.
# Leave as "" to skip the check.
WEBHOOK_SECRET = ""
# ───────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Symbol translator ──────────────────────────────────────────────────────────

# Known base symbols that MaxMillion supports
_KNOWN_BASES = ["BTC", "ETH", "SOL", "BNB", "DOGE", "XRP", "ADA", "AVAX", "MATIC", "LTC"]

def ticker_to_symbol(ticker: str) -> str:
    """
    Convert a TradingView ticker to a MaxMillion symbol.

    Examples:
        "BTCUSDT"   → "BTC/USDT"
        "ETHUSDT"   → "ETH/USDT"
        "BTC/USDT"  → "BTC/USDT"   (already correct, pass through)
        "SOLUSDT"   → "SOL/USDT"
        "BTCUSD"    → "BTC/USD"
        "UNKNOWN"   → "BTC/USDT"   (safe fallback)
    """
    ticker = ticker.upper().strip()

    # Already has a slash — pass through as-is
    if "/" in ticker:
        return ticker

    # Try to match a known base symbol at the start of the ticker
    for base in _KNOWN_BASES:
        if ticker.startswith(base):
            quote = ticker[len(base):]   # everything after the base, e.g. "USDT"
            if quote:
                return f"{base}/{quote}"
            return f"{base}/USDT"        # no quote found, default to USDT

    # Last resort: try splitting on known quote currencies only
    _KNOWN_QUOTES = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH", "BNB")
    for quote in _KNOWN_QUOTES:
        if ticker.endswith(quote) and len(ticker) > len(quote):
            base = ticker[: -len(quote)]
            if base.isalpha():
                return f"{base}/{quote}"

    log.warning(f"Could not parse ticker '{ticker}', defaulting to BTC/USDT")
    return "BTC/USDT"


# ── HTTP handler ───────────────────────────────────────────────────────────────

class WebhookHandler(BaseHTTPRequestHandler):

    # Suppress the default "GET /path HTTP/1.1 200 -" log spam
    def log_message(self, fmt, *args):
        pass

    def send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Health-check endpoint so you can verify the adapter is alive."""
        if self.path in ("/", "/health"):
            self.send_json(200, {"status": "ok", "service": "tradingview-adapter", "port": LISTEN_PORT})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self.send_json(404, {"error": "only /webhook is accepted"})
            return

        # ── 1. Read the body ───────────────────────────────────────────────────
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length)

        try:
            tv_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error(f"Bad JSON from TradingView: {exc}")
            self.send_json(400, {"error": f"invalid JSON: {exc}"})
            return

        log.info(f"TradingView alert received: {tv_payload}")

        # ── 2. Optional secret token check ────────────────────────────────────
        if WEBHOOK_SECRET:
            incoming_secret = (
                tv_payload.get("secret")
                or self.headers.get("X-Webhook-Secret", "")
            )
            if incoming_secret != WEBHOOK_SECRET:
                log.warning("Rejected: wrong secret token")
                self.send_json(403, {"error": "forbidden"})
                return

        # ── 3. Translate TradingView → MaxMillion ─────────────────────────────
        ticker = tv_payload.get("ticker", "")
        if not ticker:
            log.warning("No 'ticker' field in payload, defaulting to BTC/USDT")
        symbol = ticker_to_symbol(ticker) if ticker else "BTC/USDT"

        mm_payload = {"symbol": symbol}
        log.info(f"Forwarding to MaxMillion: {mm_payload}")

        # ── 4. Forward to MaxMillion ───────────────────────────────────────────
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(MAXMILLION_URL, json=mm_payload)
                resp.raise_for_status()
                result = resp.json()
        except httpx.ConnectError:
            log.error(f"Cannot reach MaxMillion at {MAXMILLION_URL}")
            self.send_json(502, {
                "error": "MaxMillion is not reachable",
                "url":   MAXMILLION_URL,
                "tip":   "Is MaxMillion running? Check: curl http://localhost:8082/health",
            })
            return
        except httpx.HTTPStatusError as exc:
            log.error(f"MaxMillion returned {exc.response.status_code}: {exc.response.text}")
            self.send_json(502, {
                "error":  f"MaxMillion HTTP {exc.response.status_code}",
                "detail": exc.response.text[:300],
            })
            return
        except Exception as exc:
            log.error(f"Unexpected error forwarding to MaxMillion: {exc}")
            self.send_json(500, {"error": str(exc)})
            return

        # ── 5. Return MaxMillion's result to TradingView ───────────────────────
        log.info(f"MaxMillion result: {result}")
        self.send_json(200, {
            "ok":        True,
            "symbol":    symbol,
            "mm_result": result,
        })


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookHandler)
    log.info(f"TradingView adapter listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"Forwarding trade signals → {MAXMILLION_URL}")
    log.info("Health check: http://localhost:8085/health")
    log.info("Webhook URL:  http://localhost:8085/webhook  (expose via ngrok)")
    log.info("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Adapter stopped.")
        sys.exit(0)
