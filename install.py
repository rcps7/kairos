# Kairos AI Agent — installer
# Creates a virtual environment and installs all dependencies.
# MIT License

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"


def run(cmd):
    print(">", cmd)
    return subprocess.call(cmd, shell=True)


def main():
    print("=" * 60)
    print("  KAIROS - Self-Evolving AI Agent  installer")
    print("=" * 60)

    if sys.version_info < (3, 9):
        print("[ERROR] Python 3.9+ is required.")
        return 1

    if not (VENV / "Scripts" / "python.exe").exists():
        print("Creating virtual environment...")
        run(f'"{sys.executable}" -m venv "{VENV}"')

    python = VENV / "Scripts" / "python.exe"
    pip = VENV / "Scripts" / "pip.exe"

    print("Upgrading pip...")
    run(f'"{python}" -m pip install --upgrade pip')

    print("Installing dependencies (this may take several minutes)...")
    run(f'"{pip}" install -r "{ROOT / "requirements.txt"}"')

    print()
    print("=" * 60)
    print("  Installation complete.")
    print("  Run 'run.bat' to start Kairos.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
