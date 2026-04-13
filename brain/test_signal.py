#!/usr/bin/env python3
"""
test_signal.py — simulate Metaclaw signals and manage the brain API locally.

Usage examples:
  # Health check
  python test_signal.py --health

  # Send a small test signal (low notional, no Slack prompt if threshold > 65)
  python test_signal.py --qty 0.001 --price 65000

  # Send a high-value signal (will trigger Slack approval request)
  python test_signal.py --qty 0.1 --price 65000 --strategy arb_v2

  # Kill switch controls
  python test_signal.py --kill-on
  python test_signal.py --kill-off
  python test_signal.py --status

  # List recent signals
  python test_signal.py --signals
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BRAIN_BASE_URL", "http://localhost:8080")
METACLAW_SECRET = os.getenv("METACLAW_WEBHOOK_SECRET", "")
BRAIN_API_KEY = os.getenv("BRAIN_API_KEY", "")

AUTH_HEADER = {"Authorization": f"Bearer {BRAIN_API_KEY}"}


def _sign(body: bytes) -> str:
    if not METACLAW_SECRET:
        return ""
    return "sha256=" + hmac.new(
        METACLAW_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


def health():
    resp = httpx.get(f"{BASE_URL}/healthz", timeout=5)
    data = resp.json()
    ks = data.get("kill_switch", "?")
    print(f"  Status : {data.get('status')}")
    print(f"  Kill switch : {ks}  ({data.get('kill_switch_reason', '')})")


def send_signal(symbol="BTCUSDT", side="BUY", qty=0.001, price=65000.0, strategy="test"):
    notional = qty * price
    payload = {
        "source": "metaclaw",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "notional_usd": notional,
        "strategy": strategy,
        "idempotency_key": str(uuid.uuid4()),
    }
    body = json.dumps(payload).encode()
    sig = _sign(body)

    print(f"\n  Sending: {side} {qty} {symbol} @ ${price:,.2f}  (notional ${notional:,.2f})")
    resp = httpx.post(
        f"{BASE_URL}/webhook/metaclaw",
        content=body,
        headers={"Content-Type": "application/json", "X-Metaclaw-Signature": sig},
        timeout=10,
    )
    result = resp.json()
    print(f"  Response [{resp.status_code}]: {json.dumps(result, indent=2)}")
    return result


def kill_on(reason="Test: manual enable"):
    resp = httpx.post(
        f"{BASE_URL}/killswitch/enable",
        headers=AUTH_HEADER,
        json={"reason": reason, "actor": "test_script"},
        timeout=5,
    )
    print(f"  Kill switch ON: {resp.json()}")


def kill_off(reason="Test: manual disable"):
    resp = httpx.post(
        f"{BASE_URL}/killswitch/disable",
        headers=AUTH_HEADER,
        json={"reason": reason, "actor": "test_script"},
        timeout=5,
    )
    print(f"  Kill switch OFF: {resp.json()}")


def kill_status():
    resp = httpx.get(f"{BASE_URL}/killswitch/status", headers=AUTH_HEADER, timeout=5)
    data = resp.json()
    enabled = data.get("is_enabled")
    state_str = "ON (blocking)" if enabled else "OFF (trading allowed)"
    print(f"  Kill switch  : {state_str}")
    print(f"  Reason       : {data.get('reason', '—')}")
    print(f"  Updated by   : {data.get('updated_by', '—')}  at {data.get('updated_at', '—')}")


def list_signals(limit=10, status=None):
    params = {"limit": limit}
    if status:
        params["status"] = status
    resp = httpx.get(f"{BASE_URL}/signals", headers=AUTH_HEADER, params=params, timeout=5)
    signals = resp.json()
    if not signals:
        print("  No signals found.")
        return
    print(f"\n  {'STATUS':<26} {'SIDE':<5} {'QTY':<10} {'SYMBOL':<12} {'NOTIONAL':>12}  ID")
    print("  " + "─" * 80)
    for s in signals:
        print(
            f"  {s['status']:<26} {s['side']:<5} {s['qty']:<10} {s['symbol']:<12}"
            f" ${s['notional_usd']:>10,.2f}  {s['id'][:8]}"
        )


def show_audit(limit=20):
    resp = httpx.get(f"{BASE_URL}/audit", headers=AUTH_HEADER, params={"limit": limit}, timeout=5)
    events = resp.json()
    print(f"\n  {'TIME':<28} {'EVENT':<35} {'SIGNAL':<10} ACTOR")
    print("  " + "─" * 85)
    for e in reversed(events):
        sig_short = (e.get("signal_id") or "")[:8] or "—       "
        print(
            f"  {e['created_at'][:26]:<28} {e['event_type']:<35}"
            f" {sig_short:<10} {e.get('actor') or '—'}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Brain API test CLI")
    parser.add_argument("--health", action="store_true", help="Health check")
    parser.add_argument("--kill-on", action="store_true", help="Enable kill switch")
    parser.add_argument("--kill-off", action="store_true", help="Disable kill switch")
    parser.add_argument("--status", action="store_true", help="Kill switch status")
    parser.add_argument("--signals", action="store_true", help="List recent signals")
    parser.add_argument("--audit", action="store_true", help="Show recent audit log")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--qty", type=float, default=0.001)
    parser.add_argument("--price", type=float, default=65000.0)
    parser.add_argument("--strategy", default="test_signal")
    args = parser.parse_args()

    if args.kill_on:
        kill_on()
    elif args.kill_off:
        kill_off()
    elif args.status:
        kill_status()
    elif args.signals:
        list_signals()
    elif args.audit:
        show_audit()
    elif args.health:
        health()
    else:
        # Default: health check + send a signal + show updated signal list
        print("\n── Health ──────────────────────────────────────")
        health()
        print("\n── Sending signal ──────────────────────────────")
        send_signal(
            symbol=args.symbol,
            side=args.side,
            qty=args.qty,
            price=args.price,
            strategy=args.strategy,
        )
        time.sleep(0.3)
        print("\n── Recent signals ──────────────────────────────")
        list_signals(limit=5)
        print()
