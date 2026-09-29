"""Image generation via an OpenAI-compatible images endpoint (httpx).

Disabled unless enabled in config and an API key is available (keyring or
config). Generated images are saved under <storage_root>/Kairos/Media/.
"""

import base64
import logging
import uuid
from pathlib import Path

import httpx

from kairos import config

logger = logging.getLogger(__name__)


def _conf():
    return (config.load_config().get("agent", {}) or {}).get("image", {}) or {}


def _key():
    return config._keyring_get("image_api_key") or _conf().get("api_key")


def enabled() -> bool:
    c = _conf()
    return bool(c.get("enabled")) and bool(c.get("api_url")) and bool(_key())


def generate(prompt: str, size: str = "1024x1024", save_dir: str = None) -> str:
    c = _conf()
    key = _key()
    if not enabled():
        raise PermissionError("Image generation is disabled or not configured.")
    payload = {"model": c.get("model", ""), "prompt": prompt, "size": size, "n": 1}
    r = httpx.post(c["api_url"], headers={"Authorization": f"Bearer {key}"},
                   json=payload, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"Image API {r.status_code}: {r.text[:200]}")
    data = r.json()
    item = (data.get("data") or [{}])[0]
    out_dir = Path(save_dir) if save_dir else (
        Path(config.load_config().get("storage_root", str(Path.home()))) / "Kairos" / "Media")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"img_{uuid.uuid4().hex}.png"
    if item.get("b64_json"):
        path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with httpx.stream("GET", item["url"], timeout=180) as s:
            s.raise_for_status()
            with path.open("wb") as f:
                for chunk in s.iter_bytes():
                    f.write(chunk)
    else:
        raise RuntimeError("Image API returned no image data.")
    return str(path)