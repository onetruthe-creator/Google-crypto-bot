#!/usr/bin/env python3
"""
3D Bot Monitor — serves the dashboard on port 4000
and streams live events via WebSocket on port 4001.

Sources:
  - journalctl logs (slack.service, zeroclaw.service)
  - ZeroClaw /health endpoint
  - MetaClaw /v1/models endpoint
"""

import asyncio
import json
import os
import subprocess
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx
import websockets

# ── Config ────────────────────────────────────────────────────────────────────
HTTP_PORT      = 4000
WS_PORT        = 4001
ZC_HEALTH      = "http://127.0.0.1:3000/health"
MC_URL         = "http://127.0.0.1:30000/v1/chat/completions"
OLLAMA_URL     = "http://localhost:11434/api/tags"
ZC_TOKEN       = os.environ.get("ZEROCLAW_TOKEN", "")
MONITOR_DIR    = Path(__file__).parent
# ─────────────────────────────────────────────────────────────────────────────

connected_clients: set = set()


# ── Event broadcaster ─────────────────────────────────────────────────────────

async def broadcast(event: dict):
    if not connected_clients:
        return
    msg = json.dumps(event)
    await asyncio.gather(
        *[ws.send(msg) for ws in list(connected_clients)],
        return_exceptions=True,
    )


# ── Log tailer ────────────────────────────────────────────────────────────────

def parse_log_line(line: str, service: str) -> dict | None:
    """Extract structured event from a journalctl log line."""
    if service == "slack":
        if "[dm]" in line:
            msg = line.split("[dm]")[-1].strip()[:80]
            return {"type": "message_in", "text": msg, "node": "slack"}
        if "[APPROVED]" in line:
            return {"type": "approved", "node": "metaclaw"}
        if "KEYWORD BLOCK" in line or "[BLOCKED]" in line:
            kw = line.split("matched")[-1].strip()[:40] if "matched" in line else ""
            return {"type": "blocked", "keyword": kw, "node": "metaclaw"}
        if "Webhook HTTP" in line:
            return {"type": "webhook_error", "node": "zeroclaw"}
        if "HTTP Request: POST" in line and "30000" in line:
            return {"type": "metaclaw_call", "node": "metaclaw"}
        if "HTTP Request: POST" in line and "3000/webhook" in line:
            return {"type": "zeroclaw_call", "node": "zeroclaw"}

    if service == "zeroclaw":
        if "Agent turn failed" in line:
            return {"type": "agent_error", "node": "zeroclaw"}
        if "New client paired" in line:
            return {"type": "paired", "node": "zeroclaw"}
        if "provider=" in line and "error=" in line:
            return {"type": "provider_error", "node": "ollama"}

    return None


async def tail_logs(loop: asyncio.AbstractEventLoop):
    """Tail journalctl for both services and broadcast parsed events."""
    proc = await asyncio.create_subprocess_exec(
        "journalctl", "-f", "-n", "0",
        "-u", "slack.service",
        "-u", "zeroclaw.service",
        "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        service = "slack" if "slack" in line.lower() else "zeroclaw"
        event = parse_log_line(line, service)
        if event:
            await broadcast(event)


# ── Health poller ─────────────────────────────────────────────────────────────

async def poll_health():
    """Poll node health every 5 seconds and broadcast status."""
    while True:
        status = {}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(ZC_HEALTH)
                status["zeroclaw"] = "ok" if r.status_code == 200 else "error"
        except Exception:
            status["zeroclaw"] = "offline"

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(OLLAMA_URL)
                status["ollama"] = "ok" if r.status_code == 200 else "error"
        except Exception:
            status["ollama"] = "offline"

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.post(MC_URL, json={
                    "model": "llama3.2:1b",
                    "messages": [{"role": "user", "content": "ping"}],
                }, timeout=5)
                status["metaclaw"] = "ok" if r.status_code == 200 else "error"
        except Exception:
            status["metaclaw"] = "offline"

        status["slack"] = "ok"  # If the monitor is running, slack bridge is assumed up
        await broadcast({"type": "health", "status": status})
        await asyncio.sleep(10)


# ── WebSocket handler ─────────────────────────────────────────────────────────

async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)


# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(MONITOR_DIR), **kwargs)

    def log_message(self, *args):
        pass  # suppress HTTP logs


def run_http():
    server = HTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print(f"3D Monitor HTTP  → http://0.0.0.0:{HTTP_PORT}/monitor.html")
    print(f"3D Monitor WS    → ws://0.0.0.0:{WS_PORT}")

    threading.Thread(target=run_http, daemon=True).start()

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.gather(
            tail_logs(asyncio.get_event_loop()),
            poll_health(),
        )


if __name__ == "__main__":
    asyncio.run(main())
