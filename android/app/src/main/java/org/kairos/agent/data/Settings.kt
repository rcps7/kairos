// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Non-secret settings (desktop: ~/.kairos/config.json).
package org.kairos.agent.data

import android.content.Context
import org.kairos.agent.llm.Providers

class Settings(context: Context) {
    private val p = context.getSharedPreferences("kairos_settings", Context.MODE_PRIVATE)

    var activeProvider: String
        get() = p.getString("active_llm", "moonshot")!!
        set(v) = p.edit().putString("active_llm", v).apply()

    fun apiUrl(pid: String): String =
        p.getString("api_url_$pid", null) ?: Providers.byId(pid)?.apiUrl.orEmpty()
    fun setApiUrl(pid: String, url: String) = p.edit().putString("api_url_$pid", url.trim()).apply()

    fun model(pid: String): String =
        p.getString("model_$pid", null) ?: Providers.byId(pid)?.model.orEmpty()
    fun setModel(pid: String, model: String) = p.edit().putString("model_$pid", model.trim()).apply()

    fun cachedModels(pid: String): List<String> =
        p.getString("models_$pid", null)?.split('\n')?.filter { it.isNotBlank() }
            ?: Providers.fallbackModels(pid, apiUrl(pid), model(pid))
    fun setCachedModels(pid: String, models: List<String>) =
        p.edit().putString("models_$pid", models.joinToString("\n")).apply()

    var activeCharacter: String
        get() = p.getString("active_character", "general")!!
        set(v) = p.edit().putString("active_character", v).apply()
}
