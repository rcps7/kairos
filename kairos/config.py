import copy
import json
from pathlib import Path
import keyring

CONFIG_DIR = Path.home() / ".kairos"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "storage_root": str(Path.home() / "KairosData"),
    "telegram_token": None,
    "active_llm": "moonshot",
    "llm_providers": {
        "moonshot": {
            "api_url": "https://api.moonshot.ai/v1/chat/completions",
            "api_key": None,
            "model": "kimi-k3"
        }
    },
    "peripherals": {
        "default_baud": 115200
    },
    "retention_days": 30
}


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)


def _keyring_get(key: str):
    try:
        return keyring.get_password("kairos", key)
    except Exception:
        return None


def _keyring_set(key: str, value: str):
    try:
        keyring.set_password("kairos", key, value)
        return True
    except Exception:
        return False


def load_config() -> dict:
    _ensure_config_dir()
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Backfill missing top-level keys
    for key, value in DEFAULT_CONFIG.items():
        cfg.setdefault(key, value)

    if not cfg.get("telegram_token"):
        cfg["telegram_token"] = _keyring_get("telegram_token")

    # Load LLM provider API keys from keyring
    for pid, p in cfg.get("llm_providers", {}).items():
        if not p.get("api_key"):
            p["api_key"] = _keyring_get(f"llm_api_key_{pid}")

    return cfg


def save_config(cfg: dict):
    _ensure_config_dir()
    # Work on a copy so the caller's dict keeps its secrets in memory.
    cfg = copy.deepcopy(cfg)
    token = cfg.get("telegram_token")
    if token:
        if _keyring_set("telegram_token", token):
            cfg["telegram_token"] = None

    providers = cfg.get("llm_providers", {})
    for pid, p in providers.items():
        if p.get("api_key"):
            if _keyring_set(f"llm_api_key_{pid}", p["api_key"]):
                p["api_key"] = None

    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)
