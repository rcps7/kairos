import base64
import json
import mimetypes

import httpx

from .. import config


class LLMClient:
    def __init__(self):
        cfg = config.load_config()
        self.providers = cfg.get("llm_providers", {})
        self.active_provider = cfg.get("active_llm", "moonshot")
        self.client = httpx.Client(timeout=180.0)
        self.last_usage = None

    def get_active(self) -> dict:
        return self.providers.get(self.active_provider, {})

    def list_providers(self) -> list:
        return list(self.providers.keys())

    def is_vision(self, provider_id: str = None) -> bool:
        pid = provider_id or self.active_provider
        return bool(self.providers.get(pid, {}).get("vision", False))

    def set_active(self, provider_id: str) -> bool:
        cfg = config.load_config()
        if provider_id not in cfg.get("llm_providers", {}):
            return False
        cfg["active_llm"] = provider_id
        config.save_config(cfg)
        self.active_provider = provider_id
        return True

    def add_provider(self, provider_id: str, api_url: str, api_key: str, model: str, vision: bool = False) -> bool:
        cfg = config.load_config()
        providers = cfg.setdefault("llm_providers", {})
        providers[provider_id] = {
            "api_url": api_url,
            "api_key": api_key,
            "model": model,
            "vision": bool(vision),
        }
        config.save_config(cfg)
        self.providers = providers
        return True

    def remove_provider(self, provider_id: str) -> bool:
        cfg = config.load_config()
        providers = cfg.setdefault("llm_providers", {})
        if provider_id not in providers:
            return False
        del providers[provider_id]
        if cfg.get("active_llm") == provider_id:
            cfg["active_llm"] = next(iter(providers), None)
        config.save_config(cfg)
        self.providers = providers
        self.active_provider = cfg.get("active_llm")
        return True

    def generate(self, user_prompt: str, system_prompt: str = "You are a helpful assistant.", provider_id: str = None) -> str:
        pid = provider_id or self.active_provider
        p = self.providers.get(pid)
        if not p:
            raise RuntimeError(f"LLM provider '{pid}' not configured.")
        if not p.get("api_key"):
            raise RuntimeError(f"API key missing for provider '{pid}'.")

        headers = {
            "Authorization": f"Bearer {p['api_key']}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": p.get("model"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        resp = self.client.post(p["api_url"], headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code} ({pid}): {resp.text[:500]}")
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self.last_usage = None
        try:
            u = data.get("usage") or {}
            pt = int(u.get("prompt_tokens") or 0)
            ct = int(u.get("completion_tokens") or 0)
            self.last_usage = {
                "provider": pid,
                "model": p.get("model"),
                "prompt_tokens": pt or max(1, (len(user_prompt) + len(system_prompt)) // 4),
                "completion_tokens": ct or max(1, len(content or "") // 4),
            }
        except Exception:
            self.last_usage = None
        return content

    def generate_with_images(self, user_prompt: str, image_paths, system_prompt: str = "You are a helpful assistant.", provider_id: str = None) -> str:
        """Send a text prompt plus one or more images (OpenAI-compatible format)."""
        pid = provider_id or self.active_provider
        p = self.providers.get(pid)
        if not p:
            raise RuntimeError(f"LLM provider '{pid}' not configured.")
        if not p.get("api_key"):
            raise RuntimeError(f"API key missing for provider '{pid}'.")

        content = [{"type": "text", "text": user_prompt}]
        for img in image_paths:
            try:
                mime = mimetypes.guess_type(str(img))[0] or "image/png"
                b64 = base64.b64encode(open(img, "rb").read()).decode("ascii")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            except Exception:
                continue

        headers = {
            "Authorization": f"Bearer {p['api_key']}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": p.get("model"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        }
        resp = self.client.post(p["api_url"], headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code} ({pid}): {resp.text[:500]}")
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def generate_messages(self, messages, tools=None, provider_id=None):
        """Low-level chat with an explicit message list; supports native tools."""
        pid = provider_id or self.active_provider
        p = self.providers.get(pid)
        if not p:
            raise RuntimeError(f"LLM provider '{pid}' not configured.")
        if not p.get("api_key"):
            raise RuntimeError(f"API key missing for provider '{pid}'.")
        headers = {"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"}
        payload = {"model": p.get("model"), "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        resp = self.client.post(p["api_url"], headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code} ({pid}): {resp.text[:500]}")
        data = resp.json()
        self.last_usage = None
        try:
            u = data.get("usage") or {}
            self.last_usage = {
                "provider": pid, "model": p.get("model"),
                "prompt_tokens": int(u.get("prompt_tokens") or 0) or 1,
                "completion_tokens": int(u.get("completion_tokens") or 0) or 1,
            }
        except Exception:
            self.last_usage = None
        return data.get("choices", [{}])[0].get("message", {}) or {}

    def stream_text(self, user_prompt: str, system_prompt: str = "You are a helpful assistant.",
                    provider_id: str = None):
        """Yield text deltas from an SSE chat stream (OpenAI-compatible)."""
        pid = provider_id or self.active_provider
        p = self.providers.get(pid)
        if not p:
            raise RuntimeError(f"LLM provider '{pid}' not configured.")
        if not p.get("api_key"):
            raise RuntimeError(f"API key missing for provider '{pid}'.")
        headers = {"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"}
        payload = {
            "model": p.get("model"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
        }
        self.last_usage = None
        with self.client.stream("POST", p["api_url"], headers=headers, json=payload) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"LLM error {r.status_code} ({pid}): {r.text[:300]}")
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                u = obj.get("usage")
                if u:
                    self.last_usage = {
                        "provider": pid, "model": p.get("model"),
                        "prompt_tokens": int(u.get("prompt_tokens") or 0) or 1,
                        "completion_tokens": int(u.get("completion_tokens") or 0) or 1,
                    }
                ch = (obj.get("choices", [{}])[0].get("delta", {}) or {}).get("content")
                if ch:
                    yield ch

    def close(self):
        self.client.close()
