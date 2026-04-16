#!/usr/bin/env python3
"""
ZeroClaw Universal Skill Router (port 8089)

Exposes all 137 ZeroClaw skills as callable API endpoints.
On startup it reads `zeroclaw skills list` to build a live registry.
Each skill's description becomes the system prompt for Ollama.

Endpoints:
  GET  /health          — service check
  GET  /skills          — list all available skills + descriptions
  GET  /skills/{name}   — get one skill's description
  POST /ask             — {"skill": "fintech-engineer", "question": "..."}
  POST /ask/auto        — auto-pick the best skill, {"question": "..."}

Slack prefix: "skill: <skill-name>: <question>"
  Example: "skill: fintech-engineer: how do I hedge a crypto long position?"
  Example: "skill: embedded-systems: why is my Jetson throttling?"
  Example: "skill: debugger: my FastAPI returns 422 on POST /ask"

systemd service (Jetson terminal):
  sudo tee /etc/systemd/system/skill-router.service > /dev/null << 'EOF'
  [Unit]
  Description=ZeroClaw Universal Skill Router
  After=network.target
  [Service]
  Type=simple
  User=damon
  WorkingDirectory=/home/damon/maxmillion
  ExecStart=/home/damon/maxmillion/venv/bin/python skill_router.py
  Restart=always
  RestartSec=5
  [Install]
  WantedBy=multi-user.target
  EOF
  sudo systemctl daemon-reload && sudo systemctl enable skill-router && sudo systemctl start skill-router
"""

import re
import subprocess
import logging
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
PORT         = 8089
OLLAMA_URL   = "http://localhost:11434/v1/chat/completions"
MODEL        = "zeroclaw:latest"
ZEROCLAW_BIN = "/home/damon/.cargo/bin/zeroclaw"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="ZeroClaw Skill Router", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Skill registry (loaded once at startup) ───────────────────────────────────

_SKILLS: dict[str, str] = {}   # name → description


def _load_skills() -> dict[str, str]:
    """
    Run `zeroclaw skills list` and parse the output into {name: description}.
    Falls back to a hardcoded subset if the binary isn't available.
    """
    skills: dict[str, str] = {}
    try:
        result = subprocess.run(
            [ZEROCLAW_BIN, "skills", "list"],
            capture_output=True, text=True, timeout=15
        )
        text = result.stdout + result.stderr
        # Each line looks like:  "  skill-name v0.1.0 — Description text here"
        pattern = re.compile(r"^\s{2}([\w-]+)\s+v[\d.]+\s+[—–-]\s+(.+)$")
        for line in text.splitlines():
            m = pattern.match(line)
            if m:
                skills[m.group(1)] = m.group(2).strip()
        log.info(f"[skills] loaded {len(skills)} skills from ZeroClaw")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning(f"[skills] zeroclaw not found or timed out ({e}), using fallback registry")

    # Always ensure our custom skills are present even without ZeroClaw binary
    skills.setdefault("maxmillion-trader",
        "Paper trading agent for crypto market analysis and mock trade execution.")
    skills.setdefault("fintech-engineer",
        "Financial systems engineering across ledgers, reconciliation, transfers, settlement, and compliance-sensitive transactional flows.")
    skills.setdefault("embedded-systems",
        "Embedded or hardware-adjacent work involving device constraints, firmware boundaries, timing, or low-level integration.")
    skills.setdefault("iot-engineer",
        "IoT system work involving devices, telemetry, edge communication, or cloud-device coordination.")
    skills.setdefault("python-pro",
        "Python runtime behavior, packaging, typing, testing, or framework-adjacent implementation.")
    skills.setdefault("rust-engineer",
        "Rust expertise for ownership-heavy systems code, async runtime behavior, or performance-sensitive implementation.")
    skills.setdefault("debugger",
        "Deep bug isolation across code paths, stack traces, runtime behavior, or failing tests.")
    skills.setdefault("security-engineer",
        "Infrastructure and platform security engineering across IAM, secrets, network controls, or hardening work.")
    skills.setdefault("performance-monitor",
        "Ongoing performance-signal interpretation across build, runtime, or operational metrics before deeper optimization starts.")
    skills.setdefault("legal-advisor",
        "Legal-risk spotting in product or engineering behavior, especially around terms, data handling, or externally visible commitments.")

    return skills


@app.on_event("startup")
def startup():
    global _SKILLS
    _SKILLS = _load_skills()
    log.info(f"[startup] skill router ready — {len(_SKILLS)} skills available")


# ── Ollama helper ─────────────────────────────────────────────────────────────

def _ask_ollama(system: str, user_prompt: str, timeout: int = 120) -> str:
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(OLLAMA_URL, json={
            "model":    MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user_prompt},
            ],
            "stream": False,
        })
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _build_system_prompt(skill_name: str, description: str) -> str:
    return (
        f"You are Skyp_the_Bot operating in **{skill_name}** mode.\n\n"
        f"Your expertise for this session: {description}\n\n"
        "Answer with the depth and precision of a senior specialist in this domain. "
        "Be direct and practical. If the question is outside this domain, note it "
        "briefly then still do your best to help."
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "skill-router", "port": PORT,
            "skills_loaded": len(_SKILLS)}


@app.get("/skills")
def list_skills():
    """Return all available skills sorted alphabetically."""
    return {
        "count":  len(_SKILLS),
        "skills": {k: v for k, v in sorted(_SKILLS.items())},
    }


@app.get("/skills/{skill_name}")
def get_skill(skill_name: str):
    """Return description for one skill."""
    desc = _SKILLS.get(skill_name)
    if not desc:
        # fuzzy match — find closest name
        close = [k for k in _SKILLS if skill_name.lower() in k.lower()]
        if close:
            raise HTTPException(
                status_code=404,
                detail=f"Skill '{skill_name}' not found. Did you mean: {', '.join(close[:5])}?"
            )
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")
    return {"skill": skill_name, "description": desc}


class AskRequest(BaseModel):
    skill:    str
    question: str
    timeout:  Optional[int] = 120


class AutoAskRequest(BaseModel):
    question: str
    timeout:  Optional[int] = 120


@app.post("/ask")
def ask(req: AskRequest):
    """
    Invoke a specific skill to answer a question.

    Example:
      {"skill": "fintech-engineer", "question": "How do I calculate unrealized PnL?"}
    """
    desc = _SKILLS.get(req.skill)
    if not desc:
        close = [k for k in _SKILLS if req.skill.lower() in k.lower()]
        hint  = f" Did you mean: {', '.join(close[:3])}?" if close else ""
        raise HTTPException(status_code=404, detail=f"Skill '{req.skill}' not found.{hint}")

    log.info(f"[/ask] skill={req.skill} question={req.question[:80]}")
    system = _build_system_prompt(req.skill, desc)
    try:
        answer = _ask_ollama(system, req.question, timeout=req.timeout or 120)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama timed out — try a shorter question.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    return {"skill": req.skill, "description": desc, "response": answer}


@app.post("/ask/auto")
def ask_auto(req: AutoAskRequest):
    """
    Auto-select the best skill for the question using a lightweight routing
    step, then answer with that skill's expertise.

    Example:
      {"question": "My Jetson Nano keeps thermal-throttling under load."}
    """
    # Routing prompt — small, fast, no streaming needed
    skill_list = "\n".join(f"  {k}: {v[:80]}" for k, v in sorted(_SKILLS.items()))
    router_system = (
        "You are a skill router. Given a question and a list of available expert skills, "
        "reply with ONLY the skill name (hyphenated, lowercase) that best matches. "
        "No explanation. No punctuation. Just the skill name."
    )
    router_prompt = (
        f"Available skills:\n{skill_list}\n\n"
        f"Question: {req.question}\n\n"
        "Best skill name:"
    )
    log.info(f"[/ask/auto] routing question: {req.question[:80]}")
    try:
        chosen = _ask_ollama(router_system, router_prompt, timeout=30).strip().lower()
        chosen = re.sub(r"[^a-z0-9-]", "", chosen)   # strip any stray chars
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Routing step failed: {e}")

    desc = _SKILLS.get(chosen)
    if not desc:
        # Fallback: pick first fuzzy match
        close = [k for k in _SKILLS if chosen[:6] in k]
        if close:
            chosen = close[0]
            desc   = _SKILLS[chosen]
        else:
            chosen = "debugger"
            desc   = _SKILLS.get("debugger", "General expert problem solver.")

    log.info(f"[/ask/auto] routed to skill={chosen}")
    system = _build_system_prompt(chosen, desc)
    try:
        answer = _ask_ollama(system, req.question, timeout=req.timeout or 120)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama timed out.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    return {"skill_chosen": chosen, "description": desc, "response": answer}


@app.get("/", response_class=HTMLResponse)
def index():
    """Quick visual dashboard of all skills."""
    rows = "".join(
        f"<tr><td><code>{k}</code></td><td>{v}</td></tr>"
        for k, v in sorted(_SKILLS.items())
    )
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html><head><title>ZeroClaw Skill Router</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:1000px;margin:40px auto;background:#0d1117;color:#c9d1d9}}
  h1{{color:#58a6ff}} h2{{color:#79c0ff}}
  table{{width:100%;border-collapse:collapse;margin-top:20px}}
  th{{background:#161b22;color:#58a6ff;padding:10px;text-align:left}}
  td{{padding:8px 10px;border-bottom:1px solid #21262d;vertical-align:top}}
  tr:hover td{{background:#161b22}}
  code{{color:#f78166;background:#161b22;padding:2px 6px;border-radius:4px}}
</style></head>
<body>
<h1>ZeroClaw Skill Router</h1>
<h2>{len(_SKILLS)} Skills Available</h2>
<p>POST <code>/ask</code> with <code>{{"skill":"name","question":"..."}}</code></p>
<table>
  <tr><th>Skill</th><th>Description</th></tr>
  {rows}
</table>
</body></html>""")


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"ZeroClaw Skill Router starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
