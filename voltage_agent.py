#!/usr/bin/env python3
"""
Voltage Agent — Jetson Tegrastats Monitor (port 8088)

Reads live Jetson hardware metrics (CPU, GPU, RAM, temp, power)
from tegrastats and exposes them via FastAPI.

Endpoints:
  GET  /health    — service check
  GET  /metrics   — live Jetson hardware stats
  GET  /summary   — human-readable summary string
  POST /ask       — natural language question answered by ZeroClaw/Ollama

systemd service (Jetson terminal):
  sudo tee /etc/systemd/system/voltage-agent.service > /dev/null << 'EOF'
  [Unit]
  Description=Voltage Agent - Jetson Tegrastats Monitor
  After=network.target
  [Service]
  Type=simple
  User=damon
  WorkingDirectory=/home/damon/maxmillion
  ExecStart=/home/damon/maxmillion/venv/bin/python voltage_agent.py
  Restart=always
  RestartSec=5
  [Install]
  WantedBy=multi-user.target
  EOF
  sudo systemctl daemon-reload && sudo systemctl enable voltage-agent && sudo systemctl start voltage-agent
"""

import re
import subprocess
import logging
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
PORT       = 8088
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL      = "zeroclaw:latest"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Voltage Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Tegrastats parser ─────────────────────────────────────────────────────────

def _run_tegrastats() -> str:
    """Run tegrastats once and return one line of output."""
    try:
        result = subprocess.run(
            ["tegrastats", "--interval", "500"],
            capture_output=True, text=True, timeout=3
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return lines[0] if lines else ""
    except FileNotFoundError:
        # Not a Jetson — return mock data matching real Orin/Xavier format
        return (
            "04-16-2026 12:00:00 RAM 4480/7620MB (lfb 71x4MB) "
            "SWAP 3740/9954MB (cached 33MB) "
            "CPU [2%@729,2%@729,1%@729,1%@729,1%@729,2%@729] GR3D_FREQ 0% "
            "cpu@46.093C soc2@45.312C soc0@45.5C gpu@46.843C tj@46.875C soc1@46.875C "
            "VDD_IN 4465mW/4465mW VDD_CPU_GPU_CV 518mW/518mW VDD_SOC 1395mW/1395mW"
        )
    except subprocess.TimeoutExpired:
        return ""


def parse_tegrastats(line: str) -> dict:
    """Parse a tegrastats output line into a structured dict."""
    data: dict = {"raw": line}

    # RAM: e.g. RAM 4480/7620MB
    m = re.search(r"RAM (\d+)/(\d+)MB", line)
    if m:
        data["ram_used_mb"]  = int(m.group(1))
        data["ram_total_mb"] = int(m.group(2))
        data["ram_free_mb"]  = data["ram_total_mb"] - data["ram_used_mb"]
        data["ram_pct"]      = round(data["ram_used_mb"] / data["ram_total_mb"] * 100, 1)

    # SWAP: e.g. SWAP 3740/9954MB
    m = re.search(r"SWAP (\d+)/(\d+)MB", line)
    if m:
        data["swap_used_mb"]  = int(m.group(1))
        data["swap_total_mb"] = int(m.group(2))

    # CPU: e.g. CPU [2%@729,2%@729,...]
    m = re.search(r"CPU \[([^\]]+)\]", line)
    if m:
        cores = []
        for entry in m.group(1).split(","):
            parts = entry.split("@")
            pct   = int(parts[0].replace("%", "")) if parts[0] != "off" else 0
            freq  = int(parts[1]) if len(parts) > 1 else 0
            cores.append({"pct": pct, "freq_mhz": freq})
        data["cpu_cores"]   = cores
        data["cpu_avg_pct"] = round(sum(c["pct"] for c in cores) / len(cores), 1) if cores else 0
        data["cpu_count"]   = len(cores)

    # GPU frequency: e.g. GR3D_FREQ 0%
    m = re.search(r"GR3D_FREQ (\d+)%", line)
    if m:
        data["gpu_freq_pct"] = int(m.group(1))

    # EMC (memory controller): e.g. EMC_FREQ 12%  (not always present)
    m = re.search(r"EMC_FREQ (\d+)%", line)
    if m:
        data["emc_freq_pct"] = int(m.group(1))

    # Temperatures — Orin/Xavier NX format: cpu@46.093C gpu@46.843C soc0@45.5C etc.
    for sensor in ["cpu", "gpu", "tj", "soc0", "soc1", "soc2"]:
        m = re.search(rf"(?<!\w){sensor}@([\d.]+)C", line)
        if m:
            data[f"temp_{sensor}_c"] = float(m.group(1))

    # Power rails — Orin/Xavier NX format: VDD_IN 4465mW/4465mW
    for rail, key in [
        ("VDD_IN",          "power_in_mw"),
        ("VDD_CPU_GPU_CV",  "power_cpu_gpu_mw"),
        ("VDD_SOC",         "power_soc_mw"),
        # older Nano/TX2 rails kept for compatibility
        ("POM_5V_IN",       "power_in_mw"),
        ("POM_5V_GPU",      "power_gpu_mw"),
        ("POM_5V_CPU",      "power_cpu_mw"),
    ]:
        m = re.search(rf"{re.escape(rail)} (\d+)mW/(\d+)mW", line)
        if not m:
            # older format without mW suffix: POM_5V_IN 4895/5244
            m = re.search(rf"{re.escape(rail)} (\d+)/(\d+)(?!mW)", line)
        if m:
            data[key]           = int(m.group(1))
            data[key + "_avg"]  = int(m.group(2))

    # Total board power
    if "power_in_mw" in data:
        data["total_power_w"] = round(data["power_in_mw"] / 1000, 2)

    return data


def get_metrics() -> dict:
    line = _run_tegrastats()
    if not line:
        raise HTTPException(status_code=503, detail="tegrastats returned no data")
    return parse_tegrastats(line)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "voltage-agent", "port": PORT}


@app.get("/metrics")
def metrics():
    """Return live Jetson hardware metrics as JSON."""
    return get_metrics()


@app.get("/summary")
def summary():
    """Return a short human-readable status string."""
    d = get_metrics()
    parts = []

    if "cpu_avg_pct" in d:
        parts.append(f"CPU {d['cpu_avg_pct']}%")
    if "gpu_freq_pct" in d:
        parts.append(f"GPU {d['gpu_freq_pct']}%")
    if "ram_pct" in d:
        parts.append(f"RAM {d['ram_pct']}% ({d['ram_used_mb']}/{d['ram_total_mb']} MB)")
    if "temp_cpu_c" in d:
        parts.append(f"CPU temp {d['temp_cpu_c']}°C")
    if "temp_gpu_c" in d:
        parts.append(f"GPU temp {d['temp_gpu_c']}°C")
    if "total_power_w" in d:
        parts.append(f"Power {d['total_power_w']}W")

    text = " | ".join(parts) if parts else "No data"
    return {"summary": text, "metrics": d}


class AskRequest(BaseModel):
    question: str


@app.post("/ask")
async def ask(req: AskRequest):
    """Answer a natural language question about Jetson hardware status."""
    try:
        d = get_metrics()
    except HTTPException:
        d = {}

    system = (
        "You are Skyp_the_Bot — an expert in NVIDIA Jetson hardware, embedded AI, "
        "GPU/CPU performance monitoring, power management, and thermal throttling. "
        "Answer questions about Jetson hardware metrics clearly and concisely. "
        "Always add: 'Always consult official NVIDIA docs for hardware decisions.'"
    )
    context = f"Current Jetson hardware metrics:\n{d}\n\nUser question: {req.question}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":    MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": context},
                ],
            })
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"Voltage agent error: {e}"

    return {"response": answer, "metrics": d}


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Voltage Agent starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
