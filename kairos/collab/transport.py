"""Network transports for collaboration.

Only *binding/endpoint selection* lives here; the encrypted session is handled
by ``session.py``. Direct/LAN and Tailscale are supported; ngrok is optional.
"""

import logging
import shutil
import socket
import subprocess

logger = logging.getLogger(__name__)


def detect_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def tailscale_ip():
    exe = shutil.which("tailscale") or shutil.which("tailscale.exe")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                             timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        return lines[0] if lines else None
    except Exception:
        return None


def choose_endpoint(mode: str = "direct", allow_public_bind: bool = False):
    """Return (transport, bind_host, advertised_host).

    * direct      -> bind the LAN IP (not 0.0.0.0) so we are not exposed.
    * public      -> bind 0.0.0.0 (explicit opt-in), advertise the LAN IP.
    * ts          -> bind the Tailscale IP (hides the public IP).
    """
    mode = (mode or "direct").lower()
    if mode in ("ts", "tailscale"):
        ip = tailscale_ip()
        if not ip:
            raise RuntimeError("Tailscale is not available (install/enable it first).")
        return ("ts", ip, ip)
    if mode == "public" or allow_public_bind:
        return ("direct", "0.0.0.0", detect_lan_ip())
    lan = detect_lan_ip()
    return ("direct", lan, lan)