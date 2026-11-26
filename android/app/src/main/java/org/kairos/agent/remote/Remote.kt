// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Client for the desktop remote API (kairos/remote_api.py):
// pairing link, HKDF-SHA256 key derivation and AES-256-GCM sealed requests/responses, so the phone
// can chat with and run jobs on a PC agent over the LAN. Uses only javax.crypto (no new dependency).
package org.kairos.agent.remote

import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.URLDecoder
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object RemoteCrypto {
    private val SALT = "kairos-remote".toByteArray()
    private val INFO = "kairos-remote-v1 aes-256-gcm".toByteArray()
    private val rng = SecureRandom()

    fun b64e(b: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(b)
    fun b64d(s: String): ByteArray = Base64.getUrlDecoder().decode(s.trim().trimEnd('='))

    private fun hmac(key: ByteArray, data: ByteArray): ByteArray =
        Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }.doFinal(data)

    /** RFC 5869 HKDF-SHA256 for a 32-byte output (one expand block). */
    fun deriveKey(secret: String): ByteArray {
        val ikm = b64d(secret)
        require(ikm.size >= 32) { "Pairing key is too short." }
        val prk = hmac(SALT, ikm)
        return hmac(prk, INFO + byteArrayOf(1)).copyOf(32)
    }

    fun keyId(key: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(key).joinToString("") { "%02x".format(it) }.take(8)

    fun seal(key: ByteArray, plaintext: ByteArray, aad: ByteArray, nonce: ByteArray = ByteArray(12).also { rng.nextBytes(it) }): Pair<ByteArray, ByteArray> {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        c.updateAAD(aad)
        return nonce to c.doFinal(plaintext)
    }

    fun open(key: ByteArray, nonce: ByteArray, ciphertext: ByteArray, aad: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
        c.updateAAD(aad)
        return c.doFinal(ciphertext)
    }

    fun reqAad(ts: Long) = "kairos-remote-v1|req|$ts".toByteArray()
    fun respAad(nonceB64: String) = "kairos-remote-v1|resp|$nonceB64".toByteArray()
}

data class Pairing(val host: String, val port: Int, val key: String, val name: String)

object PairingLink {
    /** Parse kairos://pair?host=..&port=..&key=..&name=.. (from `python -m kairos.remote_api pair`). */
    fun parse(link: String): Pairing {
        val t = link.trim()
        require(t.startsWith("kairos://pair?")) { "Not a Kairos pairing link." }
        val q = t.substringAfter('?').split('&').filter { '=' in it }.associate {
            it.substringBefore('=') to URLDecoder.decode(it.substringAfter('='), "UTF-8")
        }
        val host = q["host"].orEmpty()
        require(Regex("^[A-Za-z0-9.:\\-\\[\\]%]{1,100}$").matches(host)) { "Invalid host in pairing link." }
        val port = q["port"]?.toIntOrNull()?.takeIf { it in 1..65535 } ?: throw IllegalArgumentException("Invalid port in pairing link.")
        val key = q["key"].orEmpty()
        require(runCatching { RemoteCrypto.b64d(key).size >= 32 }.getOrDefault(false)) { "Invalid key in pairing link." }
        return Pairing(host, port, key, q["name"].orEmpty().ifBlank { host })
    }
}

class RemoteError(msg: String) : Exception(msg)

data class RemoteJob(val id: String, val prompt: String, val mode: String, val status: String,
                     val progress: String = "", val result: String? = null, val error: String? = null)

/** Talks to a paired PC. Calls are blocking; run them off the main thread. */
class RemoteClient(
    private val pairing: Pairing,
    private val http: OkHttpClient = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES).build(),
    private val clock: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    private val key = RemoteCrypto.deriveKey(pairing.key)
    private val kid = RemoteCrypto.keyId(key)
    private val base = "http://${if (':' in pairing.host && !pairing.host.startsWith("[")) "[${pairing.host}]" else pairing.host}:${pairing.port}"

    fun call(op: String, args: JsonObject = JsonObject(emptyMap())): JsonElement {
        val ts = clock()
        val plain = buildJsonObject { put("op", op); put("args", args) }.toString().toByteArray()
        val (nonce, ct) = RemoteCrypto.seal(key, plain, RemoteCrypto.reqAad(ts))
        val n = RemoteCrypto.b64e(nonce)
        val env = buildJsonObject { put("v", 1); put("kid", kid); put("ts", ts); put("n", n); put("c", RemoteCrypto.b64e(ct)) }
        val req = Request.Builder().url("$base/v1/rpc").post(env.toString().toRequestBody("application/json".toMediaType())).build()
        http.newCall(req).execute().use { r ->
            val body = r.body?.string().orEmpty()
            if (r.code != 200) {
                val msg = runCatching { Json.parseToJsonElement(body).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
                throw RemoteError(when (r.code) {
                    401 -> "PC rejected the request (${msg ?: "unauthorized"}). Pair again if the PC was re-paired."
                    403 -> "PC only accepts phones on the same local network."
                    429 -> "Too many failed attempts; wait a minute."
                    else -> "PC error ${r.code}: ${msg ?: body.take(200)}"
                })
            }
            val o = Json.parseToJsonElement(body).jsonObject
            val out = try {
                RemoteCrypto.open(key, RemoteCrypto.b64d(o["n"]!!.jsonPrimitive.content), RemoteCrypto.b64d(o["c"]!!.jsonPrimitive.content), RemoteCrypto.respAad(n))
            } catch (e: Exception) { throw RemoteError("Response failed verification.") }
            val res = Json.parseToJsonElement(String(out)).jsonObject
            if (res["ok"]?.jsonPrimitive?.booleanOrNull != true) throw RemoteError(res["error"]?.jsonPrimitive?.contentOrNull ?: "PC error")
            return res["result"] ?: JsonNull
        }
    }

    fun ping(): String {
        val o = call("ping").jsonObject
        val ch = o["character"]?.jsonPrimitive?.contentOrNull
        return "${o["name"]?.jsonPrimitive?.content} · Kairos ${o["version"]?.jsonPrimitive?.content}" + (ch?.let { " · $it" } ?: "")
    }

    fun chat(prompt: String): String = call("chat", buildJsonObject { put("prompt", prompt) }).jsonPrimitive.content

    fun submit(prompt: String, mode: String? = null): String =
        call("submit", buildJsonObject { put("prompt", prompt); mode?.let { put("mode", it) } }).jsonObject["id"]!!.jsonPrimitive.content

    fun job(id: String): RemoteJob = parseJob(call("job", buildJsonObject { put("id", id) }).jsonObject)

    fun jobs(): List<RemoteJob> = call("jobs").jsonArray.map { parseJob(it.jsonObject) }

    fun kill(): String = call("kill", buildJsonObject { put("confirm", true) }).jsonPrimitive.content

    /** Submit and poll until the job finishes (or [timeoutMs]). */
    fun runJob(prompt: String, mode: String? = null, timeoutMs: Long = 10 * 60_000, pollMs: Long = 1000,
               onUpdate: (RemoteJob) -> Unit = {}): RemoteJob {
        val id = submit(prompt, mode)
        val end = System.currentTimeMillis() + timeoutMs
        while (true) {
            val j = job(id); onUpdate(j)
            if (j.status == "done" || j.status == "error") return j
            if (System.currentTimeMillis() > end) throw RemoteError("Timed out waiting for job $id")
            Thread.sleep(pollMs)
        }
    }

    private fun parseJob(o: JsonObject) = RemoteJob(
        o["id"]?.jsonPrimitive?.content.orEmpty(), o["prompt"]?.jsonPrimitive?.contentOrNull.orEmpty(),
        o["mode"]?.jsonPrimitive?.contentOrNull.orEmpty(), o["status"]?.jsonPrimitive?.contentOrNull.orEmpty(),
        o["progress"]?.jsonPrimitive?.contentOrNull.orEmpty(), o["result"]?.jsonPrimitive?.contentOrNull, o["error"]?.jsonPrimitive?.contentOrNull)
}
