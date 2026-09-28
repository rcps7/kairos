"""Telegram authorization tests (A1)."""

from unittest import mock

from kairos import telegram_bot as tb


class _User:
    def __init__(self, uid):
        self.id = uid


class _Upd:
    def __init__(self, uid):
        self.effective_user = _User(uid)
        self.effective_chat = _User(uid)


def _bot():
    return tb.TelegramBot.__new__(tb.TelegramBot)


def test_allowlist():
    bot = _bot()
    with mock.patch.object(tb.config, "load_config",
                           return_value={"telegram": {"allowed_user_ids": [111, "222"]}}):
        assert bot._allowed_ids() == {111, 222}
        assert bot._authorized(_Upd(111))
        assert bot._authorized(_Upd(222))
        assert not bot._authorized(_Upd(999))


def test_empty_allowlist_denies_all():
    bot = _bot()
    with mock.patch.object(tb.config, "load_config",
                           return_value={"telegram": {"allowed_user_ids": []}}):
        assert not bot._authorized(_Upd(111))
