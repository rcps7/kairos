// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/llm/client.py.
package org.kairos.agent.llm

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

data class ChatMessage(val role: String, val content: String)
data class Usage(val promptTokens: Int, val completionTokens: Int)
data class ChatResult(val text: String, val usage: Usage?)

class LlmException(msg: String) : RuntimeException(msg)

class LlmClient(
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .build(),
) {
    // Desktop serialises provider calls with a reentrant lock; a coroutine Mutex does the same.
    private val gate = Mutex()
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun chat(
        apiUrl: String, apiKey: String, model: String, messages: List<ChatMessage>,
        temperature: Double = 0.7,
        onDelta: ((String) -> Unit)? = null,
    ): ChatResult = gate.withLock {
        withContext(Dispatchers.IO) {
            if (apiUrl.isBlank()) throw LlmException("Provider API URL is not set.")
            if (apiKey.isBlank()) throw LlmException("API key missing for this provider.")
            val stream = onDelta != null
            val body = buildJsonObject {
                put("model", model)
                put("temperature", temperature)
                put("stream", stream)
                putJsonArray("messages") {
                    messages.forEach { m -> addJsonObject { put("role", m.role); put("content", m.content) } }
                }
            }.toString()
            val req = Request.Builder().url(apiUrl)
                .header("Authorization", "Bearer $apiKey")
                .post(body.toRequestBody("application/json".toMediaType()))
                .build()
            http.newCall(req).execute().use { r ->
                if (r.code >= 400) throw LlmException("LLM ${r.code}: ${r.body?.string()?.take(200)}")
                val src = r.body ?: throw LlmException("Empty response")
                val isSse = r.header("Content-Type").orEmpty().contains("event-stream")
                // Some OpenAI-compatible servers ignore "stream": true and return a normal completion.
                if (!stream || !isSse) {
                    val res = parseCompletion(src.string())
                    if (stream) onDelta!!(res.text)
                    return@withContext res
                }
                val sb = StringBuilder()
                val reader = src.charStream().buffered()
                while (true) {
                    val line = reader.readLine() ?: break
                    val delta = parseSseLine(line) ?: continue
                    if (delta == DONE) break
                    sb.append(delta); onDelta!!(delta)
                }
                ChatResult(sb.toString(), null)
            }
        }
    }

    suspend fun listModels(apiUrl: String, apiKey: String): List<String> = withContext(Dispatchers.IO) {
        if (apiKey.isBlank()) throw LlmException("API key missing for this provider.")
        val req = Request.Builder().url(Providers.modelsUrl(apiUrl))
            .header("Authorization", "Bearer $apiKey").get().build()
        http.newCall(req).execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (r.code >= 400) throw LlmException("models ${r.code}: ${text.take(200)}")
            parseModels(text)
        }
    }

    fun parseCompletion(text: String): ChatResult {
        val o = json.parseToJsonElement(text).jsonObject
        val content = o["choices"]?.jsonArray?.firstOrNull()?.jsonObject
            ?.get("message")?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull
            ?: throw LlmException("Malformed completion: ${text.take(200)}")
        val u = o["usage"] as? JsonObject
        val usage = u?.let {
            Usage(it["prompt_tokens"]?.jsonPrimitive?.intOrNull ?: 0,
                it["completion_tokens"]?.jsonPrimitive?.intOrNull ?: 0)
        }
        return ChatResult(content, usage)
    }

    /** Returns the delta text, [DONE] for the terminator, or null for keep-alives / non-data lines. */
    fun parseSseLine(line: String): String? {
        if (!line.startsWith("data:")) return null
        val data = line.removePrefix("data:").trim()
        if (data == "[DONE]") return DONE
        if (data.isEmpty()) return null
        return runCatching {
            json.parseToJsonElement(data).jsonObject["choices"]?.jsonArray?.firstOrNull()?.jsonObject
                ?.get("delta")?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull
        }.getOrNull()
    }

    /** Port of LLMClient.list_models parsing: accepts {data:[...]}, {models:[...]} or a bare list. */
    fun parseModels(text: String): List<String> {
        val el = json.parseToJsonElement(text)
        val items: JsonArray? = when (el) {
            is JsonObject -> (el["data"] ?: el["models"]) as? JsonArray
            is JsonArray -> el
            else -> null
        }
        val out = linkedSetOf<String>()
        items?.forEach { it ->
            val id = when (it) {
                is JsonObject -> listOf("id", "name", "model").firstNotNullOfOrNull { k ->
                    it[k]?.jsonPrimitive?.contentOrNull?.takeIf { s -> s.isNotBlank() }
                }
                is JsonPrimitive -> it.contentOrNull
                else -> null
            }
            if (!id.isNullOrBlank()) out.add(id)
        }
        return out.sorted()
    }

    companion object { const val DONE = "\u0000[DONE]" }
}
