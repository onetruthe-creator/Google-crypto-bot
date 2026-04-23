#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from common import DEVICES, run_on, run_local


def check_service(device_name: str, service: str) -> str:
    result = run_on(device_name, f"systemctl is-active {service} 2>/dev/null || echo inactive")
    active = "active" in result and "inactive" not in result
    return f"  {'✅' if active else '❌'} {service}: {result.strip()}"


def device_status(device_name: str) -> str:
    device = DEVICES[device_name]
    lines = [f"[{device['desc']}]"]
    if device["local"]:
        uptime = run_local("uptime -p 2>/dev/null || systeminfo | findstr 'Up Time'")
        lines.append(f"  📍 Local — {uptime}")
    else:
        ping_cmd = f"ping -n 1 -w 2000 {device['host']}" if sys.platform == "win32" else f"ping -c 1 -W 2 {device['host']}"
        ping = run_local(ping_cmd)
        reachable = ("1 received" in ping or "TTL=" in ping or "bytes from" in ping)
        lines.append(f"  🌐 {device['host']}: {'✅ reachable' if reachable else '❌ unreachable'}")
        if not reachable:
            return "\n".join(lines)
    for svc in device.get("services", []):
        lines.append(check_service(device_name, svc))
    return "\n".join(lines)


if __name__ == "__main__":
    targets = [sys.argv[1]] if len(sys.argv) > 1 else list(DEVICES.keys())
    for name in targets:
        if name not in DEVICES:
            print(f"Unknown device '{name}'. Available: {', '.join(DEVICES)}")
        else:
            print(device_status(name))
            print()
