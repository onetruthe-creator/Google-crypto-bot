#!/usr/bin/env python3
import sys
import os
import requests

OLLAMA_URL = os.environ.get("SOVEREIGN_OLLAMA_URL", "http://10.0.0.87:11434/api/generate")
OLLAMA_MODEL = os.environ.get("SOVEREIGN_OLLAMA_MODEL", "qwen3:8b")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ollama_chat.py \"<prompt>\"")
        sys.exit(1)
    prompt = " ".join(sys.argv[1:])
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 512, "temperature": 0.7}},
            timeout=120,
        )
        r.raise_for_status()
        print(r.json().get("response", "").strip())
    except Exception as e:
        print(f"Ollama error: {e}")
