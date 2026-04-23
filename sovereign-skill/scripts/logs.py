#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from common import run_on

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: logs.py <device> <service> [lines]")
        sys.exit(1)
    device = sys.argv[1]
    service = sys.argv[2]
    lines = sys.argv[3] if len(sys.argv) > 3 else "30"
    print(run_on(device, f"journalctl -u {service} -n {lines} --no-pager 2>/dev/null"))
