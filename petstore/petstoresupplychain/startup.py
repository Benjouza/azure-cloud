#!/usr/bin/env python3
"""Startup script: installs requirements then runs main.py."""
import subprocess
import sys
import os

os.environ.setdefault("PYTHONUNBUFFERED", "1")

print("Installing dependencies...", flush=True)
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "-r", "requirements.txt"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"pip install failed: {result.stderr}", flush=True)
    sys.exit(1)
print("Dependencies installed.", flush=True)

# Now exec the main server
os.execv(sys.executable, [sys.executable, "main.py"])
