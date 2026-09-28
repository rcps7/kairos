# Kairos AI Agent — installer
# Creates a virtual environment and installs all dependencies.
# MIT License

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"


def run(args):
    print(">", " ".join(str(a) for a in args))
    return subprocess.call([str(a) for a in args])


def main():
    print("=" * 60)
    print("  KAIROS - Self-Evolving AI Agent  installer")
    print("=" * 60)

    if sys.version_info < (3, 10):
        print("[ERROR] Python 3.10+ is required.")
        return 1

    if not (VENV / "Scripts" / "python.exe").exists():
        print("Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV)])

    python = VENV / "Scripts" / "python.exe"

    print("Upgrading pip...")
    run([python, "-m", "pip", "install", "--upgrade", "pip"])

    print("Installing dependencies (this may take several minutes)...")
    if (ROOT / "requirements.lock").exists():
        req = ROOT / "requirements.lock"
    else:
        req = ROOT / "requirements.txt"
    run([python, "-m", "pip", "install", "-r", str(req)])

    print()
    print("=" * 60)
    print("  Installation complete.")
    print("  Run 'run.bat' to start Kairos.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
