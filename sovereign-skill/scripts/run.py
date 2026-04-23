#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from common import run_on

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: run.py <device> <command>")
        sys.exit(1)
    device = sys.argv[1]
    cmd = " ".join(sys.argv[2:])
    print(run_on(device, cmd))
