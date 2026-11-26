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

    // ---- Agent mode (desktop config agent.mode) ----
    var agentMode: String
        get() = p.getString("agent_mode", "chat")!!
        set(v) = p.edit().putString("agent_mode", v).apply()

    // ---- Email (desktop config "email"; the password lives in SecureStore) ----
    var emailAddress: String
        get() = p.getString("email_address", "")!!
        set(v) = p.edit().putString("email_address", v.trim()).apply()
    var imapHost: String
        get() = p.getString("imap_host", "")!!
        set(v) = p.edit().putString("imap_host", v.trim()).apply()
    var imapPort: Int
        get() = p.getInt("imap_port", 993)
        set(v) = p.edit().putInt("imap_port", v).apply()
    var smtpHost: String
        get() = p.getString("smtp_host", "")!!
        set(v) = p.edit().putString("smtp_host", v.trim()).apply()
    var smtpPort: Int
        get() = p.getInt("smtp_port", 465)
        set(v) = p.edit().putInt("smtp_port", v).apply()

    // ---- Telegram (desktop config "telegram"; the token lives in SecureStore) ----
    var telegramEnabled: Boolean
        get() = p.getBoolean("telegram_enabled", false)
        set(v) = p.edit().putBoolean("telegram_enabled", v).apply()
    var telegramAllowed: String
        get() = p.getString("telegram_allowed", "")!!
        set(v) = p.edit().putString("telegram_allowed", v).apply()

    companion object {
        /** Desktop _allowed_ids: ints from a list; invalid entries are skipped; empty denies everyone. */
        fun parseAllowedIds(raw: String): Set<Long> =
            raw.split(',', ' ', '\n', ';').mapNotNull { it.trim().toLongOrNull() }.toSet()
    }
}
