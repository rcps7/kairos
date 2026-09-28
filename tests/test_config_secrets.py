"""Config secret-handling tests (A3, A5, A8)."""

import json
import tempfile
from pathlib import Path

from kairos import config


def _point_config_at_tmp():
    root = Path(tempfile.mkdtemp(prefix="kairos_cfg_"))
    config.CONFIG_DIR = root
    config.CONFIG_FILE = root / "config.json"
    return root


def test_secrets_never_on_disk():
    _point_config_at_tmp()
    store = {}
    config._keyring_set = lambda k, v: (store.__setitem__(k, v), True)[1]
    config._keyring_get = lambda k: store.get(k)

    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["telegram_token"] = "123:ABCDEF"
    cfg["llm_providers"]["moonshot"]["api_key"] = "sk-secret-key-000000"
    cfg["email"] = {"email": "a@b.com", "password": "mailpw"}
    config.save_config(cfg)

    disk = config.CONFIG_FILE.read_text(encoding="utf-8")
    assert "123:ABCDEF" not in disk
    assert "sk-secret-key" not in disk
    assert "mailpw" not in disk
    assert store.get("email_password_a@b.com") == "mailpw"


def test_keyring_failure_keeps_secret_off_disk():
    _point_config_at_tmp()
    config._keyring_set = lambda k, v: False
    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["telegram_token"] = "TOPSECRET"
    config.save_config(cfg)
    assert "TOPSECRET" not in config.CONFIG_FILE.read_text(encoding="utf-8")


def test_deep_merge_defaults():
    _point_config_at_tmp()
    config._keyring_set = lambda k, v: True
    config.CONFIG_FILE.write_text(json.dumps({"collaboration": {"enabled": True}}),
                                  encoding="utf-8")
    loaded = config.load_config()
    assert "llm_require_approval" in loaded["collaboration"]
    assert "allowed_user_ids" in loaded["telegram"]
