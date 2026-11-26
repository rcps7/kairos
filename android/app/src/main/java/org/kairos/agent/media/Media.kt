// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/media_downloader.py: audio -> MP3, video -> MP4
// via yt-dlp. On Android yt-dlp and ffmpeg come from youtubedl-android (GPL-3.0), behind MediaEngine
// so the logic is testable on the JVM with a fake engine.
package org.kairos.agent.media

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.util.UUID

@Serializable
data class MediaItem(val id: String, val path: String, val title: String, val type: String, val createdAt: Long = System.currentTimeMillis())

/** JSON index of downloaded media (desktop MediaStore.add_media). */
class MediaIndex(private val file: File) {
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }
    @Synchronized fun list(): List<MediaItem> =
        if (!file.exists()) emptyList() else runCatching { json.decodeFromString<List<MediaItem>>(file.readText()) }.getOrDefault(emptyList())
    @Synchronized fun add(item: MediaItem) { save(list().filter { it.path != item.path } + item) }
    @Synchronized fun remove(id: String): Boolean {
        val all = list(); val hit = all.find { it.id == id } ?: return false
        File(hit.path).delete(); save(all - hit); return true
    }
    /** Drop entries whose file was deleted outside the app. */
    @Synchronized fun prune(): List<MediaItem> = list().filter { File(it.path).exists() }.also { save(it) }
    private fun save(items: List<MediaItem>) { file.parentFile?.mkdirs(); file.writeText(json.encodeToString(items)) }
}

/** Runs yt-dlp with the given options; returns stdout. */
interface MediaEngine {
    fun init()
    fun run(url: String, options: List<Pair<String, String?>>, processId: String, progress: (Float, String) -> Unit): String
    fun cancel(processId: String): Boolean
    fun version(): String?
}

object YtdlArgs {
    /** Same choices as desktop opts: best video+audio merged to MP4, or best audio extracted to MP3 192k. */
    fun options(fmt: String, outDir: File): List<Pair<String, String?>> {
        val common = listOf(
            "-o" to File(outDir, "%(title)s.%(ext)s").path,
            "--no-playlist" to null,
            "--restrict-filenames" to null,
            "--no-mtime" to null,
            "--newline" to null,
            "--print" to "after_move:filepath",
            "--progress" to null,
        )
        return common + if (fmt == "mp3") listOf(
            "-f" to "bestaudio/best", "-x" to null, "--audio-format" to "mp3", "--audio-quality" to "192K",
        ) else listOf(
            "-f" to "bestvideo+bestaudio/best", "--merge-output-format" to "mp4",
        )
    }

    /** yt-dlp prints the final path (after_move:filepath) as its own line; progress lines start with '['. */
    fun finalPath(stdout: String, outDir: File): File? = stdout.lineSequence().map { it.trim() }
        .filter { it.isNotEmpty() && !it.startsWith("[") }
        .map { File(it) }.lastOrNull { it.isFile && it.canonicalPath.startsWith(outDir.canonicalPath) }

    fun validateUrl(url: String): String {
        val u = url.trim()
        if (!Regex("^https?://[^\\s/$.?#].\\S*$", RegexOption.IGNORE_CASE).matches(u)) throw IllegalArgumentException("Enter an http(s) URL.")
        return u
    }
}

class MediaDownloader(private val engine: MediaEngine, val index: MediaIndex, val dir: File) {
    @Volatile private var ready = false

    @Synchronized fun ensureInit() { if (!ready) { engine.init(); ready = true } }

    fun download(url: String, fmt: String = "mp4", processId: String = UUID.randomUUID().toString(),
                 progress: (Float, String) -> Unit = { _, _ -> }): MediaItem {
        val u = YtdlArgs.validateUrl(url)
        val f = if (fmt.lowercase() == "mp3") "mp3" else "mp4"
        ensureInit()
        dir.mkdirs()
        val out = engine.run(u, YtdlArgs.options(f, dir), processId, progress)
        val file = YtdlArgs.finalPath(out, dir) ?: throw IllegalStateException("Download finished but no file was produced.")
        val item = MediaItem(UUID.randomUUID().toString().replace("-", ""), file.path,
            file.nameWithoutExtension.replace('_', ' '), if (f == "mp3") "audio" else "video")
        index.add(item)
        return item
    }

    fun cancel(processId: String) = engine.cancel(processId)
    fun version() = runCatching { ensureInit(); engine.version() }.getOrNull()
}
