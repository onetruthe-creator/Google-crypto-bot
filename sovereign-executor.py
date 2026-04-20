#!/usr/bin/env python3
"""
ZEROCLAW — AI Task Execution Sub-Agent
Port: 5001

Executes shell commands, scripts, and structured tasks delegated by SOVEREIGN.
Reports completion events back upstream. Security-allowlisted command set.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

# ── Configuration ─────────────────────────────────────────────────────────────

PORT = 5001
TIMEZONE = ZoneInfo("America/Denver")
BASE_DIR = Path(os.getenv("SOVEREIGN_DIR", "/home/damon/sovereign"))
LOG_PATH = BASE_DIR / "zeroclaw.log"

SOVEREIGN_URL = os.getenv("SOVEREIGN_URL", "http://localhost:8888")
METACLAW_URL = os.getenv("METACLAW_URL", "http://localhost:5002")
COMMAND_TIMEOUT = int(os.getenv("ZEROCLAW_TIMEOUT", "60"))
MAX_TASK_HISTORY = 100

# Commands permitted to run — extend deliberately, never wildcard
ALLOWED_COMMANDS = frozenset({
    "cat", "curl", "df", "du", "free", "git", "grep", "head",
    "journalctl", "ls", "pip", "pip3", "ps", "python3",
    "systemctl", "tail", "top", "wc",
})

# ── Logging ───────────────────────────────────────────────────────────────────

BASE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("ZeroClaw")

app = Flask(__name__)

task_history: List[Dict] = []
task_lock = threading.Lock()
active_tasks: Dict[str, Dict] = {}

# ── Command Execution ─────────────────────────────────────────────────────────

def is_safe_command(cmd: str) -> tuple[bool, str]:
    parts = cmd.strip().split()
    if not parts:
        return False, "empty command"
    base = Path(parts[0]).name
    if base not in ALLOWED_COMMANDS:
        return False, f"'{base}' not in allowlist"
    # Block shell metacharacters that could enable injection
    dangerous = (";", "&&", "||", "`", "$(", ">", "<", "|", "\\n")
    if any(d in cmd for d in dangerous):
        return False, f"shell metacharacter detected in: {cmd[:60]}"
    return True, ""


def run_command(cmd: str, timeout: int = COMMAND_TIMEOUT) -> Dict:
    safe, reason = is_safe_command(cmd)
    if not safe:
        log.warning("Blocked command: %s — %s", cmd[:80], reason)
        return {"success": False, "error": f"Command blocked: {reason}"}
    try:
        proc = subprocess.run(
            cmd.split(),          # no shell=True — avoids injection
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timed out after {timeout}s"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def execute_task(task_id: str, description: str) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    record: Dict[str, Any] = {
        "id": task_id,
        "ts": ts,
        "description": description,
        "status": "running",
        "result": None,
    }

    with task_lock:
        active_tasks[task_id] = record

    try:
        if description.upper().startswith("CMD:"):
            cmd = description[4:].strip()
            result = run_command(cmd)
        elif description.upper().startswith("PYTHON:"):
            # Execute a python3 one-liner safely
            code = description[7:].strip()
            result = run_command(f"python3 -c {code}")
        else:
            # Structured/descriptive task — acknowledge and surface to MetaClaw
            result = _delegate_to_brain(task_id, description)

        status = "complete" if result.get("success", True) else "failed"
        record.update({"status": status, "result": result})
        log.info("Task %s → %s", task_id, status)

    except Exception as exc:
        record.update({"status": "failed", "result": {"success": False, "error": str(exc)}})
        log.error("Task %s exception: %s", task_id, exc)

    finally:
        with task_lock:
            active_tasks.pop(task_id, None)
            task_history.append(record)
            if len(task_history) > MAX_TASK_HISTORY:
                task_history.pop(0)

    _report_to_sovereign(task_id, record)


def _delegate_to_brain(task_id: str, description: str) -> Dict:
    """For non-shell tasks, ask MetaClaw how to handle them."""
    try:
        r = requests.post(
            f"{METACLAW_URL}/task",
            json={"task_id": task_id, "description": description},
            timeout=30,
        )
        data = r.json()
        data["success"] = True
        return data
    except Exception as exc:
        return {
            "success": False,
            "error": f"MetaClaw unreachable: {exc}",
            "fallback": "Task acknowledged — MetaClaw offline, queued for retry.",
        }


def _report_to_sovereign(task_id: str, record: Dict) -> None:
    try:
        requests.post(
            f"{SOVEREIGN_URL}/events",
            json={
                "source": "zeroclaw",
                "event": f"task_{record['status']}",
                "data": {k: v for k, v in record.items() if k != "result"},
            },
            timeout=5,
        )
    except Exception:
        pass  # Non-fatal — SOVEREIGN may be restarting

# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    with task_lock:
        n_active = len(active_tasks)
    return jsonify({
        "status": "online",
        "service": "ZeroClaw",
        "active_tasks": n_active,
        "ts": datetime.now(TIMEZONE).isoformat(),
    })


@app.route("/task", methods=["POST"])
def submit_task():
    data = request.json or {}
    task_id = data.get("task_id") or str(uuid.uuid4())[:8]
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "description required"}), 400

    t = threading.Thread(
        target=execute_task, args=(task_id, description), daemon=True, name=f"Task-{task_id}"
    )
    t.start()
    log.info("Task %s queued: %s", task_id, description[:80])
    return jsonify({"task_id": task_id, "status": "started"})


@app.route("/tasks")
def list_tasks():
    with task_lock:
        active = list(active_tasks.values())
    return jsonify({"active": active, "history": task_history[-30:]})


@app.route("/tasks/<task_id>")
def get_task(task_id: str):
    with task_lock:
        if task_id in active_tasks:
            return jsonify(active_tasks[task_id])
    for t in reversed(task_history):
        if t["id"] == task_id:
            return jsonify(t)
    return jsonify({"error": "not found"}), 404


@app.route("/allowlist")
def show_allowlist():
    return jsonify({"allowed_commands": sorted(ALLOWED_COMMANDS)})

# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("ZeroClaw online — port %d (timeout: %ds)", PORT, COMMAND_TIMEOUT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
