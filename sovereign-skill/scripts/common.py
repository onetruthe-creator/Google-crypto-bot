import os
import subprocess
import paramiko

DEVICES = {
    "jetson": {
        "host": os.environ.get("SOVEREIGN_JETSON_HOST", "10.0.0.87"),
        "user": os.environ.get("SOVEREIGN_JETSON_USER", "damon"),
        "local": False,
        "services": ["zeroclaw", "maxmillions", "metaclaw", "ollama"],
        "desc": "Jetson Orin Nano",
    },
    "pi": {
        "host": os.environ.get("SOVEREIGN_PI_HOST", "10.0.0.144"),
        "user": os.environ.get("SOVEREIGN_PI_USER", "pi"),
        "local": False,
        "services": ["tax-app", "hosting-platform", "plandex"],
        "desc": "Raspberry Pi 5",
    },
    "prodesk": {
        "host": "localhost",
        "user": "",
        "local": True,
        "services": ["openclaw"],
        "desc": "HP ProDesk",
    },
}

SSH_KEY = os.path.expanduser(os.environ.get("SOVEREIGN_SSH_KEY", "~/.ssh/id_rsa"))


def run_local(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "timed out"
    except Exception as e:
        return f"error: {e}"


def run_ssh(device: dict, cmd: str, timeout: int = 30) -> str:
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(device["host"], username=device["user"], key_filename=SSH_KEY, timeout=10)
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode() + stderr.read().decode()
        ssh.close()
        return out.strip() or "(no output)"
    except Exception as e:
        return f"SSH error: {e}"


def run_on(device_name: str, cmd: str) -> str:
    device = DEVICES.get(device_name)
    if not device:
        return f"unknown device '{device_name}'. Available: {', '.join(DEVICES)}"
    return run_local(cmd) if device["local"] else run_ssh(device, cmd)
