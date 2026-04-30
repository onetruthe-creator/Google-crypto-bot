#!/usr/bin/env python3
"""
METACLAW — The Brain / Super Agent Reasoning Layer
Port: 5002

Embeds the full Super Agent skill set:
  strategic planning · task decomposition · domain routing
  Ollama orchestration · memory management · recovery reasoning
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
from flask import Flask, jsonify, request

# ── Configuration ─────────────────────────────────────────────────────────────

PORT = 5002
TIMEZONE = ZoneInfo("America/Denver")
BASE_DIR = Path(os.getenv("SOVEREIGN_DIR", str(Path.home() / "sovereign")))
LOG_PATH = BASE_DIR / "metaclaw.log"
DB_PATH = BASE_DIR / "metaclaw.db"

SOVEREIGN_URL = os.getenv("SOVEREIGN_URL", "http://localhost:8888")
ZEROCLAW_URL = os.getenv("ZEROCLAW_URL", "http://localhost:5001")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "repent-pro")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
MAX_HISTORY = 200
MAX_CONTEXT_TURNS = int(os.getenv("METACLAW_CONTEXT_TURNS", "5"))

# ── Logging ───────────────────────────────────────────────────────────────────

BASE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("MetaClaw")

app = Flask(__name__)

# ── Super Agent Identity & Prompts ────────────────────────────────────────────

_SUPER_AGENT_CORE = """\
You are the Super Agent — the top-level orchestrator of the SOVEREIGN system.

IDENTITY
Your role: think strategically, act decisively, delegate intelligently,
verify outcomes, and maintain continuity across the full system.

CORE CAPABILITIES
1.  Strategic planning and systems thinking
2.  Complex task decomposition and prioritization
3.  Expert Python engineering
4.  Flask API design and repair
5.  SQLite schema, memory, and event-log management
6.  Ollama model integration and prompt orchestration
7.  HTML/CSS/JavaScript dashboard construction and debugging
8.  Linux, systemd, networking, and deployment operations
9.  Multi-agent delegation and synthesis
10. Runtime monitoring, failure recovery, and rollback management
11. Security-aware architecture and cautious operations
12. Clear operator communication and stepwise validation

BEHAVIORAL RULES
- Always diagnose before making major changes.
- Preserve working components and isolate failures.
- Back up before risky edits.
- Verify every repair: compile → restart → endpoint test → log inspection.
- Delegate to specialist agents when depth, speed, or parallel work is needed.
- Keep memory useful, not noisy.
- Avoid repeated expensive model calls unless necessary.
- Prefer fast-loading dashboards with progressive enhancement.
- Use graceful fallbacks when model or agent services are unavailable.
- Think in phases: stabilize → verify → enrich → harden → scale.

THINKING MODES (adopt based on context)
CTO            — when planning roadmaps or architecture decisions
Senior Engineer — when implementing code or debugging
SRE            — when stabilizing a failing system
Security Lead  — when reviewing risk, auth, or exposed surfaces
Architect      — when designing for scale or new subsystems
Wise Steward   — when communicating clearly with the operator (Sirach)

MISSION
Keep SOVEREIGN alive, reliable, wise, and improving.
Turn disorder into structure, failure into signal,
fragmented components into one coherent intelligence.\
"""

_DOMAIN_OVERLAYS: Dict[str, str] = {
    "backend": (
        "MODE: Backend Engineering\n"
        "Focus on Python correctness, Flask endpoint design, SQLite schemas, "
        "service reliability, and clean error handling."
    ),
    "frontend": (
        "MODE: Frontend Dashboard\n"
        "Focus on HTML/CSS/JS correctness, fast initial load, progressive "
        "enhancement, and accessibility. Avoid blocking scripts."
    ),
    "devops": (
        "MODE: DevOps / Linux Operations\n"
        "Focus on systemd units, process supervision, networking, log rotation, "
        "deployment hygiene, and environment variable management."
    ),
    "security": (
        "MODE: Security Review\n"
        "Audit for injection risks, exposed secrets, overly broad permissions, "
        "missing authentication, and unsafe subprocess usage. Be specific."
    ),
    "recovery": (
        "MODE: Recovery / Debugging\n"
        "Diagnose the root cause first. Preserve working components. "
        "Suggest rollback if change risk is high. Give exact operator steps."
    ),
    "orchestration": (
        "MODE: Multi-Agent Orchestration\n"
        "Route tasks optimally across MetaClaw, ZeroClaw, SlackBridge, and future agents. "
        "Prefer parallel execution where safe. Synthesize results coherently."
    ),
    "memory": (
        "MODE: Memory Management\n"
        "Curate knowledge entries: remove stale noise, surface relevant context, "
        "deduplicate, and keep entries actionable."
    ),
    "planning": (
        "MODE: Strategic Planning\n"
        "Break goals into ordered, concrete phases. Identify dependencies, "
        "risks, and success criteria. Return structured JSON when asked."
    ),
}

# ── Database ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reasoning_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                domain      TEXT NOT NULL DEFAULT 'backend',
                prompt      TEXT NOT NULL,
                response    TEXT NOT NULL,
                model       TEXT,
                duration_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS plans (
                id      TEXT PRIMARY KEY,
                ts      TEXT NOT NULL,
                goal    TEXT NOT NULL,
                steps   TEXT NOT NULL,
                status  TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS knowledge (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                namespace TEXT NOT NULL DEFAULT 'global',
                key       TEXT NOT NULL,
                value     TEXT NOT NULL,
                UNIQUE(namespace, key)
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


def store_reasoning(domain: str, prompt: str, response: str, duration_ms: int) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reasoning_history (ts, domain, prompt, response, model, duration_ms) "
            "VALUES (?,?,?,?,?,?)",
            (ts, domain, prompt[:1000], response[:4000], OLLAMA_MODEL, duration_ms),
        )
        # Rolling window — prune oldest beyond MAX_HISTORY
        conn.execute(
            "DELETE FROM reasoning_history WHERE id NOT IN "
            "(SELECT id FROM reasoning_history ORDER BY id DESC LIMIT ?)",
            (MAX_HISTORY,),
        )
        conn.commit()


def get_recent_reasoning(limit: int = MAX_CONTEXT_TURNS) -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ts, domain, prompt, response FROM reasoning_history "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def knowledge_set(namespace: str, key: str, value: Any) -> None:
    ts = datetime.now(TIMEZONE).isoformat()
    val = value if isinstance(value, str) else json.dumps(value)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO knowledge (ts, namespace, key, value) VALUES (?,?,?,?) "
            "ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
            (ts, namespace, key, val),
        )
        conn.commit()


def knowledge_get(namespace: str, key: str) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM knowledge WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone()
    return row["value"] if row else None

# ── Domain Detection ──────────────────────────────────────────────────────────

_DOMAIN_KEYWORDS: List[tuple] = [
    ("security",     {"security", "vulnerability", "exploit", "injection", "secret", "auth", "permission", "cve"}),
    ("frontend",     {"dashboard", "html", "css", "javascript", "frontend", "ui", "render", "template"}),
    ("devops",       {"deploy", "systemd", "service", "nginx", "linux", "bash", "port", "network", "restart", "boot"}),
    ("recovery",     {"offline", "crash", "fail", "recover", "rollback", "debug", "error", "broken", "down"}),
    ("planning",     {"plan", "roadmap", "phase", "strategy", "goal", "milestone", "prioritize"}),
    ("orchestration",{"route", "delegate", "agent", "orchestrat", "assign", "dispatch", "coordinate"}),
    ("memory",       {"memory", "remember", "store", "knowledge", "forget", "context", "recall"}),
    ("backend",      {"flask", "api", "endpoint", "sqlite", "python", "database", "schema", "function"}),
]


def detect_domain(text: str) -> str:
    words = set(text.lower().split())
    for domain, keywords in _DOMAIN_KEYWORDS:
        if words & keywords:
            return domain
    return "backend"

# ── Prompt Construction ───────────────────────────────────────────────────────

def build_prompt(user_prompt: str, domain: str, extra_context: Optional[Dict] = None) -> str:
    overlay = _DOMAIN_OVERLAYS.get(domain, "")
    system = f"{_SUPER_AGENT_CORE}\n\n{overlay}".strip()

    # Inject recent reasoning as rolling context
    history = get_recent_reasoning()
    ctx_lines: List[str] = []
    for h in reversed(history):
        snippet_q = (h["prompt"] or "")[:100].replace("\n", " ")
        snippet_a = (h["response"] or "")[:150].replace("\n", " ")
        ctx_lines.append(f"  [{h['ts'][:19]}] Q: {snippet_q} → A: {snippet_a}")
    ctx_block = ("\n\nRECENT REASONING CONTEXT:\n" + "\n".join(ctx_lines)) if ctx_lines else ""

    extra_block = ""
    if extra_context:
        extra_block = f"\n\nCONTEXT DATA:\n{json.dumps(extra_context, indent=2)}"

    return f"{system}{ctx_block}{extra_block}\n\nTASK:\n{user_prompt}"

# ── Ollama Integration ────────────────────────────────────────────────────────

def call_ollama(
    prompt: str,
    domain: str = "backend",
    extra_context: Optional[Dict] = None,
    max_tokens: int = 800,
) -> Dict:
    full_prompt = build_prompt(prompt, domain, extra_context)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7, "num_gpu": 1},
    }
    t0 = time.time()
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        duration_ms = int((time.time() - t0) * 1000)
        if r.ok:
            data = r.json()
            text = data.get("response", "")
            store_reasoning(domain, prompt, text, duration_ms)
            log.info("Ollama [%s] %dms — %d chars", domain, duration_ms, len(text))
            return {
                "response": text,
                "domain": domain,
                "model": OLLAMA_MODEL,
                "duration_ms": duration_ms,
            }
        return {"error": f"Ollama HTTP {r.status_code}", "domain": domain}
    except requests.Timeout:
        log.warning("Ollama timeout after %ds", OLLAMA_TIMEOUT)
        return {"error": "ollama_timeout", "domain": domain,
                "fallback": "Model unavailable. Check `ollama list` and service status."}
    except Exception as exc:
        log.error("Ollama error: %s", exc)
        return {"error": str(exc), "domain": domain}

# ── Task Decomposition ────────────────────────────────────────────────────────

def decompose_goal(goal: str) -> List[str]:
    """Break a complex goal into ordered concrete steps via the model."""
    prompt = (
        f"You are a strategic planner. Decompose this goal into 3-7 ordered, concrete steps.\n"
        f"Goal: {goal}\n\n"
        f"Return ONLY a valid JSON array of step strings — no markdown, no explanation.\n"
        f'Example: ["Step 1: ...", "Step 2: ...", "Step 3: ..."]'
    )
    result = call_ollama(prompt, domain="planning", max_tokens=500)
    text = result.get("response", "")
    try:
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    except Exception:
        pass
    # Graceful fallback — single step
    return [f"Execute goal: {goal}"]


def score_task_priority(description: str) -> int:
    """Return 1 (urgent) – 5 (low) priority score based on keywords."""
    d = description.lower()
    if any(k in d for k in ("critical", "down", "offline", "fail", "crash", "urgent")):
        return 1
    if any(k in d for k in ("security", "exploit", "breach", "auth")):
        return 2
    if any(k in d for k in ("deploy", "release", "launch", "broken")):
        return 3
    if any(k in d for k in ("improve", "refactor", "optimize")):
        return 4
    return 5

# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({
        "status": "online",
        "service": "MetaClaw",
        "model": OLLAMA_MODEL,
        "ts": datetime.now(TIMEZONE).isoformat(),
    })


@app.route("/reason", methods=["POST"])
def reason():
    """Core reasoning endpoint — accepts a prompt, returns Super Agent response."""
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    domain = data.get("domain") or detect_domain(prompt)
    context = data.get("context") or {}
    max_tokens = int(data.get("max_tokens", 800))

    result = call_ollama(prompt, domain=domain, extra_context=context or None, max_tokens=max_tokens)
    return jsonify(result)


@app.route("/plan", methods=["POST"])
def plan():
    """Decompose a goal into steps and persist as a plan."""
    data = request.json or {}
    goal = data.get("goal", "").strip()
    if not goal:
        return jsonify({"error": "goal required"}), 400

    steps = decompose_goal(goal)
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(TIMEZONE).isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO plans (id, ts, goal, steps) VALUES (?,?,?,?)",
            (plan_id, ts, goal, json.dumps(steps)),
        )
        conn.commit()

    log.info("Plan %s created (%d steps): %s", plan_id, len(steps), goal[:60])
    return jsonify({"plan_id": plan_id, "goal": goal, "steps": steps, "priority": score_task_priority(goal)})


@app.route("/plans")
def list_plans():
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM plans ORDER BY ts DESC LIMIT 30"
        ).fetchall()]
    return jsonify(rows)


@app.route("/plans/<plan_id>", methods=["PATCH"])
def update_plan_status(plan_id: str):
    data = request.json or {}
    status = data.get("status", "").strip()
    if status not in ("active", "complete", "cancelled"):
        return jsonify({"error": "invalid status"}), 400
    with get_db() as conn:
        conn.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))
        conn.commit()
    return jsonify({"ok": True, "plan_id": plan_id, "status": status})


@app.route("/task", methods=["POST"])
def handle_task():
    """Inbound task dispatch from SOVEREIGN — reason and respond."""
    data = request.json or {}
    task_id = data.get("task_id", "?")
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "description required"}), 400

    domain = detect_domain(description)
    priority = score_task_priority(description)
    log.info("Task %s [domain=%s priority=%d]: %s", task_id, domain, priority, description[:80])

    result = call_ollama(description, domain=domain)
    return jsonify({"task_id": task_id, "domain": domain, "priority": priority, **result})


@app.route("/domain", methods=["POST"])
def detect():
    data = request.json or {}
    prompt = data.get("prompt", "")
    return jsonify({"domain": detect_domain(prompt)})


@app.route("/history")
def history():
    limit = min(int(request.args.get("limit", 20)), 200)
    rows = get_recent_reasoning(limit)
    return jsonify(rows)


@app.route("/knowledge", methods=["GET"])
def list_knowledge():
    namespace = request.args.get("namespace")
    with get_db() as conn:
        if namespace:
            rows = [dict(r) for r in conn.execute(
                "SELECT namespace, key, value, ts FROM knowledge WHERE namespace=? ORDER BY key",
                (namespace,)
            ).fetchall()]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT namespace, key, value, ts FROM knowledge ORDER BY namespace, key"
            ).fetchall()]
    return jsonify(rows)


@app.route("/knowledge", methods=["POST"])
def set_knowledge():
    data = request.json or {}
    ns = data.get("namespace", "global")
    key = data.get("key", "").strip()
    value = data.get("value", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    knowledge_set(ns, key, value)
    return jsonify({"ok": True, "namespace": ns, "key": key})


@app.route("/synthesize", methods=["POST"])
def synthesize():
    """Synthesize results from multiple agents into a coherent summary."""
    data = request.json or {}
    results = data.get("results", [])
    goal = data.get("goal", "")
    if not results:
        return jsonify({"error": "results required"}), 400

    combined = json.dumps(results, indent=2)
    prompt = (
        f"Goal: {goal}\n\n"
        f"Multiple agents returned these results:\n{combined}\n\n"
        f"As the Super Agent, synthesize these into a single coherent response. "
        f"Identify conflicts, fill gaps, and give the operator clear next actions."
    )
    result = call_ollama(prompt, domain="orchestration", max_tokens=1000)
    return jsonify(result)


@app.route("/diagnose", methods=["POST"])
def diagnose():
    """Deep diagnostic reasoning for a failing component."""
    data = request.json or {}
    component = data.get("component", "").strip()
    symptoms = data.get("symptoms", "").strip()
    logs = data.get("logs", "")
    if not component:
        return jsonify({"error": "component required"}), 400

    prompt = (
        f"Component: {component}\n"
        f"Symptoms: {symptoms}\n"
        f"Recent logs:\n{logs[:2000]}\n\n"
        f"As an SRE, provide: (1) root cause hypothesis, "
        f"(2) 3 exact diagnostic commands, (3) most likely fix."
    )
    result = call_ollama(prompt, domain="recovery", extra_context=data, max_tokens=900)
    return jsonify(result)

# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    knowledge_set("metaclaw", "boot_ts", datetime.now(TIMEZONE).isoformat())
    knowledge_set("metaclaw", "model", OLLAMA_MODEL)
    log.info("MetaClaw Super Agent Brain online — port %d (model: %s)", PORT, OLLAMA_MODEL)
    app.run(host="0.0.0.0", port=PORT, debug=False)
