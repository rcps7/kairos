// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/main.py LLM_PRESETS.
package org.kairos.agent.llm

data class ProviderPreset(val id: String, val name: String, val apiUrl: String, val model: String)

object Providers {
    val PRESETS = listOf(
        ProviderPreset("moonshot", "Moonshot AI (Kimi)", "https://api.moonshot.ai/v1/chat/completions", "kimi-k3"),
        ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com/chat/completions", "deepseek-chat"),
        ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
        ProviderPreset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1/chat/completions", "openrouter/auto"),
        ProviderPreset("groq", "Groq", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
        ProviderPreset("custom", "Custom (OpenAI-compatible)", "", ""),
    )

    /** Curated fallback models used when /models is unreachable (same as desktop). */
    val FALLBACK_MODELS = mapOf(
        "moonshot" to listOf("kimi-k3", "kimi-k2-0905-preview", "kimi-k2-turbo-preview",
            "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
        "deepseek" to listOf("deepseek-chat", "deepseek-reasoner"),
        "openai" to listOf("gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3-mini", "o1-mini"),
        "openrouter" to listOf("openrouter/auto"),
        "groq" to listOf("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"),
    )

    /**
     * Port of main.fallback_models. Desktop matches presets with `url in preset_url`, which is true for an
     * empty URL and pulls in every preset's models; here an empty URL matches nothing (see AUDIT A8).
     */
    fun fallbackModels(providerId: String, apiUrl: String = "", current: String? = null): List<String> {
        val models = FALLBACK_MODELS[providerId].orEmpty().toMutableList()
        val url = apiUrl.lowercase()
        if (url.isNotBlank()) for (preset in PRESETS) {
            val pu = preset.apiUrl.lowercase()
            if (pu.isNotBlank() && (url.contains(pu) || pu.contains(url)))
                FALLBACK_MODELS[preset.id].orEmpty().forEach { if (it !in models) models.add(it) }
        }
        if (!current.isNullOrBlank() && current !in models) models.add(0, current)
        return models
    }

    fun byId(id: String): ProviderPreset? = PRESETS.firstOrNull { it.id == id }

    /** Derive the OpenAI-style /models endpoint from the chat URL (port of LLMClient.models_url). */
    fun modelsUrl(apiUrl: String): String {
        var url = apiUrl.trim()
        for (suffix in listOf("/chat/completions", "/completions", "/responses")) {
            if (url.endsWith(suffix)) { url = url.dropLast(suffix.length); break }
        }
        url = url.trimEnd('/')
        return if (url.endsWith("/models")) url else "$url/models"
    }
}
