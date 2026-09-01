"""Kairos Watchdog / Kill Switch.

A lightweight, standalone process (stdlib only) that supervises the Kairos
agent. It can:

  * force-terminate Kairos on demand (kill switch), triggered by:
      - creating the kill-switch file
      - sending "KILL" to the local kill socket
      - running with ``--kill``
  * auto-kill Kairos if its heartbeat goes stale (i.e. the agent hung / went
    rogue and stopped writing its heartbeat).

Usage:
  python -m kairos.watchdog            # run the monitor loop
  python -m kairos.watchdog --kill     # engage the kill switch immediately
"""

import argparse
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".kairos"
HEARTBEAT_FILE = CONFIG_DIR / "heartbeat"
PID_FILE = CONFIG_DIR / "kairos.pid"
KILLSWITCH_FILE = CONFIG_DIR / "KILLSWITCH"

DEFAULT_HEARTBEAT_TIMEOUT = 60  # seconds
DEFAULT_KILL_PORT = 50055


def read_pid():
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def kill_process(pid):
    """Terminate the process with the given PID. Returns True on success."""
    if pid is None:
        print("[watchdog] no kairos.pid found.", file=sys.stderr)
        return False
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=15,
            )
            print(f"[watchdog] terminated Kairos PID {pid}.")
            return True
        except Exception as e:
            print(f"[watchdog] taskkill failed: {e}", file=sys.stderr)
            return False
    else:
        import os
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"[watchdog] terminated Kairos PID {pid}.")
            return True
        except Exception as e:
            print(f"[watchdog] kill failed: {e}", file=sys.stderr)
            return False


class KillSocketServer(threading.Thread):
    """Listens on localhost and triggers the kill switch on a KILL command."""

    def __init__(self, port, on_kill, host="127.0.0.1"):
        super().__init__(daemon=True)
        self.port = port
        self.host = host
        self.on_kill = on_kill
        self._stop = threading.Event()

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self.host, self.port))
        except OSError as e:
            print(f"[watchdog] kill socket bind failed: {e}", file=sys.stderr)
            return
        srv.listen(5)
        srv.settimeout(1.0)
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(64).decode("utf-8", "ignore").strip().upper()
                except OSError:
                    continue
                if data in ("KILL", "SHUTDOWN", "STOP"):
                    print(f"[watchdog] KILL command received from {addr}")
                    self.on_kill()
                    break
        try:
            srv.close()
        except OSError:
            pass

    def stop(self):
        self._stop.set()


def monitor(timeout=DEFAULT_HEARTBEAT_TIMEOUT, port=DEFAULT_KILL_PORT):
    killed = threading.Event()

    def do_kill():
        kill_process(read_pid())
        killed.set()

    print("[watchdog] Kairos watchdog active.")
    print(f"[watchdog] kill switch file : {KILLSWITCH_FILE}")
    print(f"[watchdog] kill socket      : 127.0.0.1:{port} (send 'KILL')")
    print(f"[watchdog] heartbeat timeout: {timeout}s")

    kill_srv = KillSocketServer(port, do_kill)
    kill_srv.start()

    try:
        while not killed.is_set():
            # 1) Kill-switch file (one-shot trigger)
            if KILLSWITCH_FILE.exists():
                try:
                    KILLSWITCH_FILE.unlink()
                except OSError:
                    pass
                print("[watchdog] kill-switch file detected.")
                do_kill()
                break

            # 2) Stale heartbeat -> agent is unresponsive
            if HEARTBEAT_FILE.exists():
                try:
                    age = time.time() - HEARTBEAT_FILE.stat().st_mtime
                except OSError:
                    age = 0
                if age > timeout:
                    print(
                        f"[watchdog] heartbeat stale ({int(age)}s). "
                        "Kairos unresponsive - engaging kill switch."
                    )
                    do_kill()
                    break

            time.sleep(1)
    finally:
        kill_srv.stop()

    print("[watchdog] exiting.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Kairos watchdog / kill switch")
    parser.add_argument(
        "--kill", action="store_true",
        help="engage the kill switch immediately and exit",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_HEARTBEAT_TIMEOUT,
        help="heartbeat timeout in seconds (default 60)",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_KILL_PORT,
        help="kill socket port (default 50055)",
    )
    args = parser.parse_args(argv)

    if args.kill:
        kill_process(read_pid())
    else:
        monitor(args.timeout, args.port)


if __name__ == "__main__":
    main()
