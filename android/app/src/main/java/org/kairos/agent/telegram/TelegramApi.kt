// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Minimal Telegram Bot API client (long polling) with OkHttp.
// Desktop uses python-telegram-bot; Android talks to the same HTTPS Bot API directly.
package org.kairos.agent.telegram

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

val TOKEN_RE = Regex("^\\d{6,}:[A-Za-z0-9_\\-]{30,}$")
fun validateTokenFormat(token: String?): Boolean = TOKEN_RE.matches((token ?: "").trim())

class TelegramException(val code: Int, msg: String) : RuntimeException(msg)

data class TgUpdate(
    val updateId: Long,
    val userId: Long?,
    val chatId: Long?,
    val text: String?,
    val messageId: Long?,
    val callbackId: String? = null,
    val callbackData: String? = null,
)

class TelegramApi(
    private val token: String,
    private val base: String = "https://api.telegram.org",
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS).readTimeout(70, TimeUnit.SECONDS).build(),
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun call(method: String, params: JsonObject = JsonObject(emptyMap())): JsonElement = withContext(Dispatchers.IO) {
        val req = Request.Builder().url("$base/bot$token/$method")
            .post(params.toString().toRequestBody("application/json".toMediaType())).build()
        http.newCall(req).execute().use { r ->
            val body = r.body?.string().orEmpty()
            val o = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
            if (o == null || o["ok"]?.jsonPrimitive?.booleanOrNull != true) {
                val desc = o?.get("description")?.jsonPrimitive?.contentOrNull ?: "HTTP ${r.code}"
                if (r.code == 401) throw TelegramException(401, "Telegram rejected the token (401 Unauthorized). " +
                    "Create or regenerate it with @BotFather, then set it in the Connect tab.")
                throw TelegramException(r.code, "Telegram error: $desc")
            }
            o["result"] ?: JsonNull
        }
    }

    suspend fun getMe(): String = call("getMe").jsonObject["username"]?.jsonPrimitive?.contentOrNull.orEmpty()

    suspend fun getUpdates(offset: Long, timeoutSec: Int = 50): List<TgUpdate> =
        call("getUpdates", buildJsonObject {
            put("offset", offset); put("timeout", timeoutSec)
            putJsonArray("allowed_updates") { add("message"); add("callback_query") }
        }).jsonArray.map { parseUpdate(it.jsonObject) }

    suspend fun sendMessage(chatId: Long, text: String, buttons: List<Pair<String, String>>? = null): Long =
        call("sendMessage", buildJsonObject {
            put("chat_id", chatId); put("text", text.take(4000).ifEmpty { "…" })
            if (buttons != null) putJsonObject("reply_markup") {
                putJsonArray("inline_keyboard") { addJsonArray { buttons.forEach { (label, data) -> addJsonObject { put("text", label); put("callback_data", data) } } } }
            }
        }).jsonObject["message_id"]?.jsonPrimitive?.longOrNull ?: 0L

    suspend fun editMessage(chatId: Long, messageId: Long, text: String) {
        try {
            call("editMessageText", buildJsonObject { put("chat_id", chatId); put("message_id", messageId); put("text", text.take(4000).ifEmpty { "…" }) })
        } catch (e: TelegramException) {
            if (e.message?.contains("not modified") != true) throw e
        }
    }

    suspend fun answerCallback(id: String, text: String? = null, alert: Boolean = false) {
        call("answerCallbackQuery", buildJsonObject { put("callback_query_id", id); if (text != null) put("text", text); put("show_alert", alert) })
    }

    companion object {
        fun parseUpdate(u: JsonObject): TgUpdate {
            val id = u["update_id"]!!.jsonPrimitive.long
            u["callback_query"]?.jsonObject?.let { cq ->
                val msg = cq["message"]?.jsonObject
                return TgUpdate(id, cq["from"]?.jsonObject?.get("id")?.jsonPrimitive?.longOrNull,
                    msg?.get("chat")?.jsonObject?.get("id")?.jsonPrimitive?.longOrNull, null,
                    msg?.get("message_id")?.jsonPrimitive?.longOrNull,
                    cq["id"]?.jsonPrimitive?.contentOrNull, cq["data"]?.jsonPrimitive?.contentOrNull)
            }
            val m = u["message"]?.jsonObject
            return TgUpdate(id, m?.get("from")?.jsonObject?.get("id")?.jsonPrimitive?.longOrNull,
                m?.get("chat")?.jsonObject?.get("id")?.jsonPrimitive?.longOrNull,
                m?.get("text")?.jsonPrimitive?.contentOrNull, m?.get("message_id")?.jsonPrimitive?.longOrNull)
        }
    }
}
