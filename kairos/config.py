import copy
import json
import logging
import threading
from pathlib import Path
import keyring

from kairos import safety

logger = logging.getLogger(__name__)

_config_lock = threading.Lock()

CONFIG_DIR = Path.home() / ".kairos"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "storage_root": str(Path.home() / "KairosData"),
    "telegram_token": None,
    "telegram": {
        "allowed_user_ids": []
    },
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
    "retention_days": 30,
    "setup_done": False,
    "mirofish": {
        "enabled": False,
        "base_url": "http://localhost:5001",
        "zep_api_key": None
    },
    "update": {
        "last_check": 0
    },
    "council": {
        "members": [],
        "mode": "standard"
    },
    "active_character": "general",
    "character": {
        "dir_name": "AGENT_CHARACTER"
    },
    "graph_memory": {
        "enabled": True,
        "db_path": None,
        "backfilled": False,
        "require_approval": True,
        "auto_approve": False,
        "extract_on_chat": True,
        "use_in_chat": True,
        "use_in_tools": True,
        "use_in_skills": True,
        "use_in_council": True,
        "use_in_predict": True,
        "max_nodes": 12,
        "max_memories": 6,
        "dedup_distance": 0.15
    },
    "collaboration": {
        "enabled": True,
        "display_name": "",
        "transport": "direct",
        "listen_port": 7777,
        "allow_public_bind": False,
        "allow_private_targets": False,
        "allow_remote_llm": False,
        "llm_require_approval": True,
        "max_sessions": 4,
        "max_file_bytes": 536870912,
        "accept_timeout": 60,
        "idle_timeout": 300
    },
    "agent": {
        "native_tools": False,
        "streaming": True,
        "file_root": None,
        "allow_file_write": True,
        "allow_shell": False,
        "skill_sandbox": "subprocess",
        "budgets": {
            "daily_tokens": 0
        },
        "image": {
            "enabled": False,
            "api_url": "",
            "api_key": None,
            "model": ""
        }
    },
    "scheduler": {
        "enabled": True,
        "poll_seconds": 5
    },
    "mcp": {
        "enabled": False,
        "servers": {}
    },
    "connectors": {
        "github": {"enabled": False, "token": None},
        "notion": {"enabled": False, "token": None}
    },
    "discord": {
        "enabled": False,
        "allowed_user_ids": [],
        "token": None
    }
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


def _deep_merge(defaults: dict, cfg: dict) -> dict:
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(cfg.get(k), dict):
            _deep_merge(v, cfg[k])
    return cfg


def _write_raw(cfg: dict):
    safety.atomic_write_text(CONFIG_FILE, json.dumps(cfg, indent=4))
    safety.restrict_file(CONFIG_FILE)


def load_config() -> dict:
    _ensure_config_dir()
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Recursively backfill missing defaults (nested dicts included).
    _deep_merge(DEFAULT_CONFIG, cfg)

    if not cfg.get("telegram_token"):
        cfg["telegram_token"] = _keyring_get("telegram_token")

    for pid, p in cfg.get("llm_providers", {}).items():
        if not p.get("api_key"):
            p["api_key"] = _keyring_get(f"llm_api_key_{pid}")

    mirofish = cfg.setdefault("mirofish", {})
    if not mirofish.get("zep_api_key"):
        mirofish["zep_api_key"] = _keyring_get("mirofish_zep_api_key")

    # Email password: load from keyring; migrate any plaintext copy out of the file.
    email = cfg.setdefault("email", {})
    addr = (email.get("email") or "").strip()
    if addr:
        if not email.get("password"):
            email["password"] = _keyring_get(f"email_password_{addr}")
        pwd = email.get("password")
        if pwd:
            if _keyring_set(f"email_password_{addr}", pwd):
                email["password"] = None
                try:
                    _write_raw(cfg)
                except Exception:
                    pass

    return cfg


def save_config(cfg: dict):
    _ensure_config_dir()
    with _config_lock:
        cfg = copy.deepcopy(cfg)

        # Secrets are NEVER written to disk: store in keyring, and null them in
        # the file even if the keyring is unavailable.
        token = cfg.get("telegram_token")
        cfg["telegram_token"] = None
        if token and not _keyring_set("telegram_token", token):
            logger.warning("Keyring unavailable; Telegram token not written to disk.")

        for pid, p in cfg.get("llm_providers", {}).items():
            key = p.get("api_key")
            p["api_key"] = None
            if key and not _keyring_set(f"llm_api_key_{pid}", key):
                logger.warning("Keyring unavailable; API key for '%s' not written to disk.", pid)

        mirofish = cfg.setdefault("mirofish", {})
        zkey = mirofish.get("zep_api_key")
        mirofish["zep_api_key"] = None
        if zkey and not _keyring_set("mirofish_zep_api_key", zkey):
            logger.warning("Keyring unavailable; MiroFish key not written to disk.")

        email = cfg.setdefault("email", {})
        epwd = email.get("password")
        email["password"] = None
        addr = (email.get("email") or "").strip()
        if epwd and addr and not _keyring_set(f"email_password_{addr}", epwd):
            logger.warning("Keyring unavailable; email password not written to disk.")

        _write_raw(cfg)
