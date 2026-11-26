// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. `fdroid` product flavour: no prebuilt yt-dlp/Python/ffmpeg
// binaries, so on-device media download is unavailable. Everything else works; use the `full` build
// (IzzyOnDroid / GitHub Releases) or the paired PC for downloads.
package org.kairos.agent.media

import android.content.Context

private class UnavailableEngine : MediaEngine {
    override fun available(): Boolean = false
    override fun init() {}
    override fun run(url: String, options: List<Pair<String, String?>>, processId: String, progress: (Float, String) -> Unit): String =
        throw IllegalStateException(
            "On-device media download is not available in this build. Install the 'full' build, " +
                "or download on the paired PC.")
    override fun cancel(processId: String): Boolean = false
    override fun version(): String? = null
}

/** `fdroid` flavour: media download is disabled (no non-free / prebuilt binaries). */
object MediaEngines {
    fun create(context: Context): MediaEngine = UnavailableEngine()

    fun update(context: Context): String =
        throw IllegalStateException("yt-dlp is not included in this build.")
}
