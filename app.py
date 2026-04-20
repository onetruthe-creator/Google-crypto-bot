#!/usr/bin/env python3
"""
SOVEREIGN — Super Agent Orchestrator
Port: 8888

The top-level coordinator of all sub-agents and subsystems.
Monitors health, routes tasks, persists memory, drives recovery.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, render_template_string, request

# ── Configuration ─────────────────────────────────────────────────────────────

PORT = 8888
TIMEZONE = ZoneInfo("America/Denver")
BASE_DIR = Path(os.getenv("SOVEREIGN_DIR", "/home/damon/sovereign"))
DB_PATH = BASE_DIR / "sovereign.db"
LOG_PATH = BASE_DIR / "sovereign.log"

METACLAW_URL = os.getenv("METACLAW_URL", "http://localhost:5002")
ZEROCLAW_URL = os.getenv("ZEROCLAW_URL", "http://localhost:5001")
SLACK_BRIDGE_URL = os.getenv("SLACK_BRIDGE_URL", "http://localhost:5003")

AGENT_URLS: Dict[str, str] = {
    "metaclaw": METACLAW_URL,
    "zeroclaw": ZEROCLAW_URL,
    "slack_bridge": SLACK_BRIDGE_URL,
}

HEALTH_INTERVAL = int(os.getenv("HEALTH_INTERVAL", "30"))

# ── Logging ───────────────────────────────────────────────────────────────────

BASE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("SOVEREIGN")

app = Flask(__name__)

# ── Database ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                level     TEXT NOT NULL DEFAULT 'INFO',
                source    TEXT NOT NULL,
                event     TEXT NOT NULL,
                data      TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                ts_created  TEXT NOT NULL,
                ts_updated  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                agent       TEXT,
                description TEXT NOT NULL,
                result      TEXT,
                error       TEXT
            );
            CREATE TABLE IF NOT EXISTS memory (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                namespace TEXT NOT NULL DEFAULT 'global',
                key       TEXT NOT NULL,
                value     TEXT NOT NULL,
                UNIQUE(namespace, key)
            );
            CREATE TABLE IF NOT EXISTS agent_states (
                agent     TEXT PRIMARY KEY,
                last_seen TEXT,
                status    TEXT DEFAULT 'unknown',
                info      TEXT
            );
        """)
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def log_event(source: str, event: str, level: str = "INFO", data: Any = None) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (ts, level, source, event, data) VALUES (?,?,?,?,?)",
            (ts, level, source, event, json.dumps(data) if data is not None else None),
        )
        conn.commit()
    log.log(getattr(logging, level, logging.INFO), "[%s] %s", source, event)


def memory_set(namespace: str, key: str, value: Any) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    val = value if isinstance(value, str) else json.dumps(value)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO memory (ts, namespace, key, value) VALUES (?,?,?,?) "
            "ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
            (ts, namespace, key, val),
        )
        conn.commit()


def memory_get(namespace: str, key: str) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM memory WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone()
        return row["value"] if row else None

# ── Agent Health ──────────────────────────────────────────────────────────────

def check_agent(name: str, url: str) -> Dict:
    try:
        r = requests.get(f"{url}/health", timeout=3)
        status = "online" if r.status_code == 200 else "degraded"
        info = r.json() if r.ok else {"http_status": r.status_code}
    except Exception as exc:
        status = "offline"
        info = {"error": str(exc)}

    ts = datetime.now(TIMEZONE).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO agent_states (agent, last_seen, status, info) VALUES (?,?,?,?) "
            "ON CONFLICT(agent) DO UPDATE SET "
            "last_seen=excluded.last_seen, status=excluded.status, info=excluded.info",
            (name, ts, status, json.dumps(info)),
        )
        conn.commit()

    if status == "offline":
        log_event("health_monitor", f"{name} is OFFLINE", "WARNING", info)

    return {"agent": name, "status": status, "info": info, "ts": ts}


def health_monitor() -> None:
    while True:
        for name, url in AGENT_URLS.items():
            check_agent(name, url)
        time.sleep(HEALTH_INTERVAL)

# ── Task Routing ──────────────────────────────────────────────────────────────

_ROUTE_MAP: List[tuple] = [
    ({"reason", "plan", "think", "analyze", "decide", "strategize", "brainstorm"}, "metaclaw"),
    ({"run", "execute", "bash", "command", "script", "deploy", "install", "restart"}, "zeroclaw"),
    ({"slack", "message", "notify", "alert", "send", "post"}, "slack_bridge"),
]


def route_task(description: str) -> str:
    words = set(description.lower().split())
    for keywords, agent in _ROUTE_MAP:
        if words & keywords:
            return agent
    return "metaclaw"


def create_task(description: str, agent: Optional[str] = None) -> str:
    task_id = str(uuid.uuid4())[:8]
    ts = datetime.now(TIMEZONE).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO tasks (id, ts_created, ts_updated, status, agent, description) "
            "VALUES (?,?,?,?,?,?)",
            (task_id, ts, ts, "pending", agent, description),
        )
        conn.commit()
    log_event("SOVEREIGN", f"task_created:{task_id}", data={"description": description, "agent": agent})
    return task_id


def update_task(task_id: str, status: str, result: Any = None, error: Optional[str] = None) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE tasks SET status=?, ts_updated=?, result=?, error=? WHERE id=?",
            (status, ts, json.dumps(result) if result is not None else None, error, task_id),
        )
        conn.commit()


def dispatch_to_agent(task_id: str, description: str, agent: str) -> Dict:
    url = AGENT_URLS.get(agent)
    if not url:
        return {"error": f"unknown agent: {agent}"}
    try:
        r = requests.post(
            f"{url}/task",
            json={"task_id": task_id, "description": description},
            timeout=60,
        )
        return r.json()
    except requests.Timeout:
        return {"error": f"{agent} timed out"}
    except Exception as exc:
        return {"error": str(exc)}

# ── Recovery ──────────────────────────────────────────────────────────────────

def attempt_recovery(agent: str) -> Dict:
    log_event("SOVEREIGN", f"recovery_requested:{agent}", "WARNING")
    try:
        r = requests.post(
            f"{METACLAW_URL}/reason",
            json={
                "prompt": (
                    f"Agent '{agent}' is offline. As an SRE, diagnose the most likely cause "
                    f"and give the operator 3 exact recovery steps."
                ),
                "domain": "recovery",
                "context": {"failing_agent": agent, "url": AGENT_URLS.get(agent)},
            },
            timeout=20,
        )
        plan = r.json()
    except Exception as exc:
        plan = {"error": str(exc), "fallback": f"Check logs and restart {agent} manually."}
    log_event("SOVEREIGN", f"recovery_plan_generated:{agent}", data=plan)
    return plan

# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({
        "status": "online",
        "service": "SOVEREIGN",
        "version": "2.0-superagent",
        "ts": datetime.now(TIMEZONE).isoformat(),
    })


@app.route("/status")
def status():
    with get_db() as conn:
        agents = [dict(r) for r in conn.execute("SELECT * FROM agent_states").fetchall()]
        recent_events = [dict(r) for r in conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 30"
        ).fetchall()]
        pending_tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending','running') ORDER BY ts_created DESC"
        ).fetchall()]
    return jsonify({
        "agents": agents,
        "recent_events": recent_events,
        "pending_tasks": pending_tasks,
        "ts": datetime.now(TIMEZONE).isoformat(),
    })


@app.route("/task", methods=["POST"])
def submit_task():
    data = request.json or {}
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "description required"}), 400

    agent = data.get("agent") or route_task(description)
    task_id = create_task(description, agent)
    update_task(task_id, "running")

    result = dispatch_to_agent(task_id, description, agent)

    if "error" in result:
        update_task(task_id, "failed", error=result["error"])
        log_event("SOVEREIGN", f"task_failed:{task_id}", "ERROR", result)
    else:
        update_task(task_id, "complete", result=result)
        log_event("SOVEREIGN", f"task_complete:{task_id}")

    return jsonify({"task_id": task_id, "agent": agent, "result": result})


@app.route("/tasks")
def list_tasks():
    limit = min(int(request.args.get("limit", 50)), 200)
    with get_db() as conn:
        tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks ORDER BY ts_created DESC LIMIT ?", (limit,)
        ).fetchall()]
    return jsonify(tasks)


@app.route("/events")
def list_events():
    limit = min(int(request.args.get("limit", 100)), 500)
    level = request.args.get("level", "").upper() or None
    with get_db() as conn:
        if level:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM events WHERE level=? ORDER BY id DESC LIMIT ?", (level, limit)
            ).fetchall()]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]
    return jsonify(rows)


@app.route("/memory", methods=["GET"])
def list_memory():
    namespace = request.args.get("namespace")
    with get_db() as conn:
        if namespace:
            rows = [dict(r) for r in conn.execute(
                "SELECT namespace, key, value, ts FROM memory WHERE namespace=? ORDER BY key",
                (namespace,)
            ).fetchall()]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT namespace, key, value, ts FROM memory ORDER BY namespace, key"
            ).fetchall()]
    return jsonify(rows)


@app.route("/memory", methods=["POST"])
def set_memory():
    data = request.json or {}
    ns = data.get("namespace", "global")
    key = data.get("key", "").strip()
    value = data.get("value", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    memory_set(ns, key, value)
    log_event("SOVEREIGN", f"memory_set:{ns}/{key}")
    return jsonify({"ok": True, "namespace": ns, "key": key})


@app.route("/agents/status")
def agents_status():
    results = {name: check_agent(name, url) for name, url in AGENT_URLS.items()}
    return jsonify(results)


@app.route("/agents/recover", methods=["POST"])
def recover_agent():
    data = request.json or {}
    agent = data.get("agent", "").strip()
    if agent not in AGENT_URLS:
        return jsonify({"error": f"unknown agent: {agent}"}), 400
    plan = attempt_recovery(agent)
    return jsonify({"agent": agent, "recovery_plan": plan})


# Inbound event sink — ZeroClaw and others post completion notices here
@app.route("/events", methods=["POST"])
def inbound_event():
    data = request.json or {}
    source = data.get("source", "unknown")
    event = data.get("event", "unknown")
    log_event(source, event, data=data.get("data"))
    return jsonify({"ok": True})


@app.route("/dashboard")
def dashboard():
    return render_template_string(_DASHBOARD_HTML)

# ── Dashboard ─────────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOVEREIGN — Super Agent</title>
<style>
:root {
  --bg:#0a0a0f; --surface:#12121a; --border:#1e1e2e;
  --accent:#7c3aed; --cyan:#06b6d4; --green:#10b981;
  --yellow:#f59e0b; --red:#ef4444; --text:#e2e8f0; --muted:#64748b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Courier New',monospace;padding:20px;font-size:14px}
header{display:flex;justify-content:space-between;align-items:center;
       margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:16px}
h1{color:var(--accent);font-size:1.4rem;letter-spacing:.12em}
.sub{color:var(--muted);font-size:.72rem;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.card h2{font-size:.72rem;color:var(--muted);text-transform:uppercase;
         letter-spacing:.1em;margin-bottom:12px}
.agent-row{display:flex;justify-content:space-between;align-items:center;
           padding:7px 0;border-bottom:1px solid var(--border)}
.agent-row:last-child{border-bottom:none}
.badge{font-size:.68rem;padding:2px 8px;border-radius:999px;font-weight:600}
.online{background:rgba(16,185,129,.15);color:var(--green)}
.offline{background:rgba(239,68,68,.15);color:var(--red)}
.degraded,.unknown{background:rgba(245,158,11,.15);color:var(--yellow)}
.evt{padding:5px 0;border-bottom:1px solid var(--border);font-size:.72rem;line-height:1.5}
.evt:last-child{border-bottom:none}
.ts{color:var(--muted)}
.INFO{color:var(--cyan)}.WARNING{color:var(--yellow)}.ERROR{color:var(--red)}
.tr{padding:5px 0;border-bottom:1px solid var(--border);font-size:.72rem}
.tr:last-child{border-bottom:none}
.complete{color:var(--green)}.pending{color:var(--yellow)}
.running{color:var(--cyan)}.failed{color:var(--red)}
.btn{background:var(--accent);color:#fff;border:none;padding:6px 14px;
     border-radius:4px;cursor:pointer;font-size:.78rem;font-family:inherit}
.btn:hover{opacity:.85}
#dispatch-form{display:flex;gap:8px;margin-top:8px}
#dispatch-form input{flex:1;background:var(--bg);border:1px solid var(--border);
  color:var(--text);padding:7px 10px;border-radius:4px;font-family:inherit;font-size:.78rem}
#dispatch-form button{background:var(--cyan);color:var(--bg);border:none;
  padding:7px 14px;border-radius:4px;cursor:pointer;font-weight:700;font-size:.78rem}
#dispatch-result{margin-top:7px;font-size:.72rem;color:var(--cyan);min-height:18px}
.empty{color:var(--muted);font-size:.75rem;text-align:center;padding:14px}
.ts-badge{color:var(--muted);font-size:.72rem}
.wide{grid-column:span 2}
@media(max-width:640px){.wide{grid-column:span 1}}
</style>
</head>
<body>
<header>
  <div>
    <h1>◈ SOVEREIGN</h1>
    <div class="sub">Super Agent Orchestration Layer &mdash; v2.0</div>
  </div>
  <div style="display:flex;gap:12px;align-items:center">
    <span class="ts-badge" id="clock"></span>
    <button class="btn" onclick="loadAll()">↻ Refresh</button>
  </div>
</header>

<div class="grid">
  <div class="card">
    <h2>Agent Health</h2>
    <div id="agents"></div>
  </div>
  <div class="card">
    <h2>Dispatch Task</h2>
    <form id="dispatch-form" onsubmit="submitTask(event)">
      <input id="task-input" type="text" placeholder="Describe task for Super Agent…" autocomplete="off">
      <button type="submit">→ Send</button>
    </form>
    <div id="dispatch-result"></div>
  </div>
</div>

<div class="grid">
  <div class="card wide">
    <h2>Event Log</h2>
    <div id="events"></div>
  </div>
  <div class="card">
    <h2>Tasks</h2>
    <div id="tasks"></div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);

async function fetchJ(url) {
  const r = await fetch(url);
  return r.json();
}

async function loadAgents() {
  const data = await fetchJ('/agents/status');
  const el = $('agents');
  const entries = Object.entries(data);
  if (!entries.length) { el.innerHTML = '<div class="empty">No agents registered</div>'; return; }
  el.innerHTML = entries.map(([name, d]) =>
    `<div class="agent-row"><span>${name}</span>
     <span class="badge ${d.status}">${d.status}</span></div>`
  ).join('');
}

async function loadEvents() {
  const data = await fetchJ('/events?limit=40');
  const el = $('events');
  if (!data.length) { el.innerHTML = '<div class="empty">No events yet</div>'; return; }
  el.innerHTML = data.map(e =>
    `<div class="evt">
       <span class="ts">${(e.ts||'').slice(11,19)}</span>
       <span class="${e.level}"> [${e.level}]</span>
       <span style="color:#94a3b8"> ${e.source}</span> &mdash; ${e.event}
     </div>`
  ).join('');
}

async function loadTasks() {
  const data = await fetchJ('/tasks?limit=25');
  const el = $('tasks');
  if (!data.length) { el.innerHTML = '<div class="empty">No tasks yet</div>'; return; }
  el.innerHTML = data.map(t =>
    `<div class="tr">
       <span class="${t.status}">[${t.status}]</span>
       <span style="color:#94a3b8"> ${t.agent||'?'}</span>
       &mdash; ${(t.description||'').slice(0,55)}
     </div>`
  ).join('');
}

async function submitTask(e) {
  e.preventDefault();
  const inp = $('task-input');
  const out = $('dispatch-result');
  const desc = inp.value.trim();
  if (!desc) return;
  out.textContent = 'Routing…';
  try {
    const r = await fetch('/task', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: desc})
    });
    const d = await r.json();
    out.textContent = `→ ${d.agent}: ${JSON.stringify(d.result).slice(0,140)}`;
    inp.value = '';
    loadTasks();
  } catch(err) {
    out.textContent = 'Error: ' + err.message;
  }
}

function tick() {
  $('clock').textContent = new Date().toLocaleTimeString();
}

async function loadAll() {
  tick();
  await Promise.all([loadAgents(), loadEvents(), loadTasks()]);
}

loadAll();
setInterval(loadAll, 15000);
setInterval(tick, 1000);
</script>
</body>
</html>"""

# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    memory_set("sovereign", "boot_ts", datetime.now(TIMEZONE).isoformat())
    log_event("SOVEREIGN", "super_agent_boot", data={"port": PORT, "agents": list(AGENT_URLS.keys())})
    threading.Thread(target=health_monitor, daemon=True, name="HealthMonitor").start()
    log.info("SOVEREIGN Super Agent online — port %d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
