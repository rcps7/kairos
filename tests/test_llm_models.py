"""Tests for provider model-listing URL derivation and fallback model lists."""

import pytest

from kairos.llm.client import LLMClient


def _client(api_url):
    c = LLMClient.__new__(LLMClient)
    c.providers = {"p": {"api_url": api_url}}
    c.active_provider = "p"
    return c


def test_models_url_derivation():
    assert _client("https://api.openai.com/v1/chat/completions").models_url() == \
        "https://api.openai.com/v1/models"
    assert _client("https://api.deepseek.com/chat/completions").models_url() == \
        "https://api.deepseek.com/models"
    assert _client("https://api.groq.com/openai/v1/chat/completions").models_url() == \
        "https://api.groq.com/openai/v1/models"
    # already a /models endpoint
    assert _client("https://x.example/v1/models").models_url() == \
        "https://x.example/v1/models"


def test_fallback_models():
    pytest.importorskip("PySide6")
    from kairos.main import fallback_models
    assert "kimi-k3" in fallback_models("moonshot", {})
    assert "gpt-4o-mini" in fallback_models("openai", {})
    # the currently-configured model is always included
    assert fallback_models("custom", {"model": "my-model"})[0] == "my-model"
