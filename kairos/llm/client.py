import httpx

from .. import config


class LLMClient:
    def __init__(self):
        cfg = config.load_config()
        self.providers = cfg.get("llm_providers", {})
        self.active_provider = cfg.get("active_llm", "moonshot")
        self.client = httpx.Client(timeout=180.0)

    def get_active(self) -> dict:
        return self.providers.get(self.active_provider, {})

    def list_providers(self) -> list:
        return list(self.providers.keys())

    def set_active(self, provider_id: str) -> bool:
        cfg = config.load_config()
        if provider_id not in cfg.get("llm_providers", {}):
            return False
        cfg["active_llm"] = provider_id
        config.save_config(cfg)
        self.active_provider = provider_id
        return True

    def add_provider(self, provider_id: str, api_url: str, api_key: str, model: str) -> bool:
        cfg = config.load_config()
        providers = cfg.setdefault("llm_providers", {})
        providers[provider_id] = {
            "api_url": api_url,
            "api_key": api_key,
            "model": model
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
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def close(self):
        self.client.close()
