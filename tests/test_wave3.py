"""Wave 3 tests: image generation, browser availability, Discord auth."""

import base64
import tempfile
from pathlib import Path
from unittest import mock

from kairos import imagegen, browser
from kairos.discord_bot import DiscordBot


def test_imagegen():
    cfg = {"agent": {"image": {"enabled": True, "api_url": "https://x/v1/images",
                               "model": "dall-e", "api_key": None}},
           "storage_root": tempfile.mkdtemp()}
    payload = base64.b64encode(b"\x89PNG\r\n").decode()
    fake = mock.Mock(status_code=200)
    fake.json.return_value = {"data": [{"b64_json": payload}]}
    with mock.patch("kairos.config.load_config", return_value=cfg), \
         mock.patch("kairos.config._keyring_get", return_value="sk-key"), \
         mock.patch("kairos.imagegen.httpx.post", return_value=fake):
        out = imagegen.generate("a cat", save_dir=tempfile.mkdtemp())
        assert Path(out).exists() and Path(out).read_bytes().startswith(b"\x89PNG")


def test_browser_available_flag():
    assert isinstance(browser.available(), bool)


def test_discord_auth():
    cfg = {"discord": {"enabled": True, "allowed_user_ids": [111, "222"]}}
    with mock.patch("kairos.config.load_config", return_value=cfg):
        bot = DiscordBot.__new__(DiscordBot)
        assert bot.allowed_ids() == {111, 222}
        assert bot._authorized(111) and bot._authorized(222)
        assert not bot._authorized(999)
