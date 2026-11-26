// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. download_media tool (desktop toolkit), gated by download_media.
package org.kairos.agent.agent

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.kairos.agent.media.MediaDownloader

class MediaTools(
    private val characters: CharacterRegistry,
    private val media: () -> MediaDownloader,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String {
        if (call.name != "download_media") return next?.run(call) ?: "(unknown tool: ${call.name})"
        if (!characters.can("download_media")) return "(tool not permitted: download_media)"
        val url = call.args["url"].orEmpty()
        val fmt = call.args["format"] ?: call.args["fmt"] ?: "mp4"
        return withContext(Dispatchers.IO) {
            try { val m = media().download(url, fmt); "Downloaded ${m.type}: ${m.title}\nSaved to: ${m.path}" }
            catch (e: Exception) { "(download error: ${e.message})" }
        }
    }
}
