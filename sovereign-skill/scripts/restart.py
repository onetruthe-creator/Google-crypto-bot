#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from common import run_on

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: restart.py <device> <service>")
        sys.exit(1)
    device = sys.argv[1]
    service = sys.argv[2]
    result = run_on(device, f"sudo systemctl restart {service} 2>&1 && echo 'restarted ok'")
    print(result)
