// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Offline speech recognition with Vosk (Apache-2.0) for devices
// without a system recognition service (common on de-Googled / F-Droid phones). The model is not
// bundled: the user downloads one (about 40 MB) from alphacephei.com in the Media & Voice screen.
package org.kairos.agent.voice

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.InputStream
import java.util.zip.ZipInputStream

object VoskModels {
    const val DEFAULT_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

    /** Vosk returns {"partial": "..."} or {"text": "..."}; extract the words. */
    fun text(json: String?): String = runCatching {
        val o = Json.parseToJsonElement(json ?: "").jsonObject
        (o["text"] ?: o["partial"])?.jsonPrimitive?.content.orEmpty().trim()
    }.getOrDefault("")

    /** Unzip [input] into [dest], refusing entries that escape it (zip-slip). Returns the model root. */
    fun unzipModel(input: InputStream, dest: File): File {
        val base = dest.canonicalFile.also { it.deleteRecursively(); it.mkdirs() }
        ZipInputStream(input.buffered()).use { zin ->
            while (true) {
                val e = zin.nextEntry ?: break
                val out = File(base, e.name).canonicalFile
                if (!out.path.startsWith(base.path + File.separator)) throw SecurityException("Bad zip entry: ${e.name}")
                if (e.isDirectory) out.mkdirs() else { out.parentFile?.mkdirs(); out.outputStream().use { zin.copyTo(it) } }
            }
        }
        return modelRoot(base) ?: throw IllegalStateException("The archive does not contain a Vosk model.")
    }

    /** A Vosk model folder has an "am" (acoustic model) directory and a "conf" directory. */
    fun modelRoot(dir: File): File? {
        if (File(dir, "am").isDirectory && File(dir, "conf").isDirectory) return dir
        return dir.listFiles()?.filter { it.isDirectory }?.firstNotNullOfOrNull { c ->
            c.takeIf { File(it, "am").isDirectory && File(it, "conf").isDirectory }
        }
    }

    fun installed(modelsDir: File): File? = File(modelsDir, "model").takeIf { it.isDirectory }?.let { modelRoot(it) }

    fun download(url: String, modelsDir: File, http: OkHttpClient = OkHttpClient(), progress: (Long, Long) -> Unit = { _, _ -> }): File {
        if (!url.startsWith("https://")) throw IllegalArgumentException("Model URL must be https://")
        http.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (!r.isSuccessful) throw IllegalStateException("Model download failed: HTTP ${r.code}")
            val body = r.body ?: throw IllegalStateException("Empty response")
            val total = body.contentLength()
            var done = 0L
            val counting = object : java.io.FilterInputStream(body.byteStream()) {
                override fun read(b: ByteArray, off: Int, len: Int): Int =
                    super.read(b, off, len).also { if (it > 0) { done += it; progress(done, total) } }
            }
            return unzipModel(counting, File(modelsDir, "model"))
        }
    }
}

/** Same callbacks as [Listener], backed by Vosk. RECORD_AUDIO must already be granted. */
class VoskListener(
    private val modelDir: File,
    private val level: (Float) -> Unit,
    private val partial: (String) -> Unit,
    private val result: (String) -> Unit,
    private val fail: (String) -> Unit,
) {
    private var model: org.vosk.Model? = null
    private var service: org.vosk.android.SpeechService? = null
    @Volatile private var done = false

    private fun finish(block: () -> Unit) { if (!done) { done = true; level(0f); block(); stop() } }

    fun start() {
        stop(); done = false
        try {
            val m = model ?: org.vosk.Model(modelDir.path).also { model = it }
            val rec = org.vosk.Recognizer(m, 16000f)
            service = org.vosk.android.SpeechService(rec, 16000f).also { s ->
                s.startListening(object : org.vosk.android.RecognitionListener {
                    override fun onPartialResult(hypothesis: String?) {
                        val t = VoskModels.text(hypothesis); if (t.isNotEmpty() && !done) { level(0.6f); partial(t) }
                    }
                    override fun onResult(hypothesis: String?) {
                        val t = VoskModels.text(hypothesis); if (t.isNotEmpty()) finish { result(t) }
                    }
                    override fun onFinalResult(hypothesis: String?) {
                        val t = VoskModels.text(hypothesis)
                        finish { if (t.isNotEmpty()) result(t) else fail("Didn't catch that — try again.") }
                    }
                    override fun onError(exception: Exception?) { finish { fail("Offline speech error: ${exception?.message}") } }
                    override fun onTimeout() { finish { fail("Didn't catch that — try again.") } }
                }, 15000)
            }
        } catch (e: Exception) { fail("Offline speech error: ${e.message}") }
    }

    fun stop() { val s = service; service = null; s?.run { runCatching { cancel(); shutdown() } } }
}
