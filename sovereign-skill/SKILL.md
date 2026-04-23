---
name: sovereign
description: Device management skill — check health, run commands, tail logs, and restart services on Jetson, Raspberry Pi 5, and local ProDesk via SSH.
version: 1.0.0
tools:
  - shell
---

# Sovereign Device Manager

You can manage three devices using this skill:

| Device   | Alias     | Host          |
|----------|-----------|---------------|
| Jetson Orin Nano | `jetson` | 10.0.0.87 |
| Raspberry Pi 5   | `pi`     | 10.0.0.144 |
| HP ProDesk (local) | `prodesk` | localhost |

## Available Scripts

All scripts are in the `scripts/` folder of this skill. Run them with `python3 <script> [args]`.

### Check device/service health
```
python3 scripts/status.py [device]
```
- No argument: checks all devices
- With device name: checks that device only

### Run a shell command on a device
```
python3 scripts/run.py <device> <command>
```
Example: `python3 scripts/run.py pi df -h`

### Tail service logs
```
python3 scripts/logs.py <device> <service> [lines]
```
Example: `python3 scripts/logs.py jetson zeroclaw 50`

### Restart a service
```
python3 scripts/restart.py <device> <service>
```
Example: `python3 scripts/restart.py jetson ollama`

### Chat with Ollama (Jetson)
```
python3 scripts/ollama_chat.py "<prompt>"
```

## Configuration

Device hosts, users, and SSH key path are read from environment variables.
Set them in your `.env` or OpenClaw secrets:

```
SOVEREIGN_SSH_KEY=~/.ssh/id_rsa
SOVEREIGN_JETSON_HOST=10.0.0.87
SOVEREIGN_JETSON_USER=damon
SOVEREIGN_PI_HOST=10.0.0.144
SOVEREIGN_PI_USER=pi
SOVEREIGN_OLLAMA_URL=http://10.0.0.87:11434/api/generate
SOVEREIGN_OLLAMA_MODEL=qwen3:8b
```

## Usage Examples

When a user asks:
- "status of all devices" → run `scripts/status.py`
- "is the Jetson online?" → run `scripts/status.py jetson`
- "restart ollama on the Jetson" → run `scripts/restart.py jetson ollama`
- "show me the last logs for zeroclaw" → run `scripts/logs.py jetson zeroclaw`
- "how much disk space is left on the Pi?" → run `scripts/run.py pi df -h`
- "chat: summarize my tasks" → run `scripts/ollama_chat.py "summarize my tasks"`
