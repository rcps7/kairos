// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. MediaEngine backed by youtubedl-android (yt-dlp + Python +
// ffmpeg, GPL-3.0). Native binaries are executed from nativeLibraryDir, so jniLibs use legacy packaging.
// Only compiled into the `full` product flavour.
package org.kairos.agent.media

import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest

class YtDlpEngine(private val context: Context) : MediaEngine {
    override fun init() {
        YoutubeDL.getInstance().init(context.applicationContext)
        FFmpeg.getInstance().init(context.applicationContext)
    }

    override fun run(url: String, options: List<Pair<String, String?>>, processId: String, progress: (Float, String) -> Unit): String {
        val req = YoutubeDLRequest(url)
        options.forEach { (k, v) -> if (v == null) req.addOption(k) else req.addOption(k, v) }
        val res = YoutubeDL.getInstance().execute(req, processId) { pct, eta, line -> progress(pct, if (eta > 0) "$line (ETA ${eta}s)" else line) }
        if (res.exitCode != 0) throw IllegalStateException(res.err.lineSequence().lastOrNull { it.isNotBlank() } ?: "yt-dlp exited with ${res.exitCode}")
        return res.out
    }

    override fun cancel(processId: String) = YoutubeDL.getInstance().destroyProcessById(processId)
    override fun version(): String? = YoutubeDL.getInstance().version(context) ?: "bundled"

    /** Update yt-dlp itself (sites change often). Network use, user-triggered only. */
    fun update(): String = YoutubeDL.getInstance().updateYoutubeDL(context.applicationContext)?.name ?: "unknown"
}

/** `full` flavour: media download is available via yt-dlp. */
object MediaEngines {
    fun create(context: Context): MediaEngine = YtDlpEngine(context)

    fun update(context: Context): String = YtDlpEngine(context).update()
}
