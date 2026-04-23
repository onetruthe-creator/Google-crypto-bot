import os
import re
import subprocess
import logging
import requests
import paramiko
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("sovereign")

app = App(token=os.environ["SLACK_BOT_TOKEN"])

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

DEVICES = {
    "jetson": {
        "host": "localhost",
        "user": os.environ.get("JETSON_USER", "damon"),
        "key_path": os.path.expanduser(os.environ.get("SSH_KEY_PATH", "~/.ssh/id_rsa")),
        "desc": "Jetson Orin Nano",
        "local": True,
        "services": ["zeroclaw", "maxmillions", "metaclaw", "ollama"],
    },
    "prodesk": {
        "host": os.environ.get("PRODESK_HOST", ""),
        "user": os.environ.get("PRODESK_USER", "Owner"),
        "key_path": os.path.expanduser(os.environ.get("SSH_KEY_PATH", "~/.ssh/id_rsa")),
        "desc": "HP ProDesk (OpenClaw)",
        "local": False,
        "services": ["OpenSSHd", "openclaw"],
    },
    "pi": {
        "host": os.environ.get("PI_HOST", "10.0.0.144"),
        "user": os.environ.get("PI_USER", "pi"),
        "key_path": os.path.expanduser(os.environ.get("SSH_KEY_PATH", "~/.ssh/id_rsa")),
        "desc": "Raspberry Pi 5",
        "local": False,
        "services": ["tax-app", "hosting-platform", "plandex"],
    },
}


def run_local(cmd: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout + result.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "timed out"
    except Exception as e:
        return f"error: {e}"


def run_ssh(device: dict, cmd: str, timeout: int = 30) -> str:
    if not device.get("host"):
        return f"host not configured"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            device["host"],
            username=device["user"],
            key_filename=device["key_path"],
            timeout=10,
        )
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode() + stderr.read().decode()
        ssh.close()
        return out.strip() or "(no output)"
    except Exception as e:
        return f"SSH error: {e}"


def run_on(device_name: str, cmd: str) -> str:
    device = DEVICES.get(device_name)
    if not device:
        return f"unknown device: {device_name}"
    return run_local(cmd) if device["local"] else run_ssh(device, cmd)


def check_service(device_name: str, service: str) -> str:
    result = run_on(device_name, f"systemctl is-active {service} 2>/dev/null || echo inactive")
    active = "active" in result and "inactive" not in result
    return f"{'✅' if active else '❌'} {service}: {result.strip()}"


def device_status(device_name: str) -> str:
    device = DEVICES.get(device_name)
    if not device:
        return f"unknown device: {device_name}"
    lines = [f"*{device['desc']}*"]
    if device["local"]:
        uptime = run_local("uptime -p")
        lines.append(f"📍 Local — {uptime}")
    else:
        ping = run_local(f"ping -c 1 -W 2 {device['host']} 2>/dev/null | grep -c '1 received' || echo 0")
        reachable = ping.strip() == "1"
        lines.append(f"🌐 {device['host']}: {'✅ reachable' if reachable else '❌ unreachable'}")
        if not reachable:
            return "\n".join(lines)
    for svc in device.get("services", []):
        lines.append(check_service(device_name, svc))
    return "\n".join(lines)


def ask_ollama(prompt: str, max_tokens: int = 512) -> str:
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.7},
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"Ollama error: {e}"


def parse_command(text: str):
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    parts = text.split(None, 2)
    cmd = parts[0].lower() if parts else "help"
    args = parts[1:] if len(parts) > 1 else []
    return cmd, args


def handle_command(text: str) -> str:
    cmd, args = parse_command(text)

    if cmd == "status":
        if args:
            return device_status(args[0])
        sections = [device_status(d) for d in DEVICES]
        return "\n\n".join(sections)

    elif cmd == "run":
        if len(args) < 2:
            return "Usage: `run <device> <command>`\nDevices: jetson, prodesk, pi"
        shell_cmd = " ".join(args[1:])
        return f"```{run_on(args[0], shell_cmd)}```"

    elif cmd == "logs":
        if len(args) < 2:
            return "Usage: `logs <device> <service>`"
        return f"```{run_on(args[0], f'journalctl -u {args[1]} -n 30 --no-pager 2>/dev/null')}```"

    elif cmd == "restart":
        if len(args) < 2:
            return "Usage: `restart <device> <service>`"
        result = run_on(args[0], f"sudo systemctl restart {args[1]} 2>&1")
        return f"Restarted `{args[1]}` on `{args[0]}`:\n```{result}```"

    elif cmd == "chat":
        if not args:
            return "Usage: `chat <message>`"
        return ask_ollama(" ".join(args))

    elif cmd == "devices":
        lines = ["*Connected Devices*"]
        for name, d in DEVICES.items():
            host = "localhost" if d["local"] else d["host"]
            lines.append(f"• `{name}` — {d['desc']} ({host})")
        return "\n".join(lines)

    elif cmd == "help":
        return (
            "*Sovereign Bot*\n"
            "`status` — health of all devices\n"
            "`status <device>` — single device (jetson, prodesk, pi)\n"
            "`run <device> <command>` — run a shell command\n"
            "`logs <device> <service>` — last 30 log lines\n"
            "`restart <device> <service>` — restart a systemd service\n"
            "`chat <message>` — ask Ollama (qwen3:8b)\n"
            "`devices` — list all devices\n"
            "`help` — this message"
        )

    else:
        return f"Unknown command: `{cmd}`. Try `help`."


@app.event("app_mention")
def handle_mention(event, say):
    say(handle_command(event.get("text", "")))


@app.event("message")
def handle_dm(event, say):
    if event.get("channel_type") == "im":
        say(handle_command(event.get("text", "")))


if __name__ == "__main__":
    log.info("Sovereign Bot starting...")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
