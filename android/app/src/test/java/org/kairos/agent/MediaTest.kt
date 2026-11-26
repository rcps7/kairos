// SPDX-License-Identifier: GPL-3.0-or-later
// Media download logic (desktop media_downloader.py) with a fake yt-dlp engine, plus the tool gate.
package org.kairos.agent

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.media.*
import java.io.File
import java.nio.file.Files

class MediaTest {
    class FakeEngine(val fail: String? = null) : MediaEngine {
        var inits = 0; var lastOptions: List<Pair<String, String?>> = emptyList()
        override fun init() { inits++ }
        override fun run(url: String, options: List<Pair<String, String?>>, processId: String, progress: (Float, String) -> Unit): String {
            fail?.let { throw IllegalStateException(it) }
            lastOptions = options
            val tmpl = options.first { it.first == "-o" }.second!!
            val ext = if (options.any { it.first == "-x" }) "mp3" else "mp4"
            val f = File(tmpl.replace("%(title)s.%(ext)s", "My_Clip.$ext")); f.writeText("data")
            progress(50f, "[download]  50.0% of 1MiB"); progress(100f, "[download] 100%")
            return "[download]  50.0% of 1MiB\n[download] 100%\n${f.path}\n"
        }
        override fun cancel(processId: String) = true
        override fun version() = "2025.11.12"
    }

    private fun dir(): File = Files.createTempDirectory("kmedia").toFile()

    @Test fun optionsMatchDesktop() {
        val d = dir()
        val mp3 = YtdlArgs.options("mp3", d).toMap()
        assertEquals("bestaudio/best", mp3["-f"]); assertEquals("mp3", mp3["--audio-format"]); assertEquals("192K", mp3["--audio-quality"])
        assertTrue("-x" in mp3); assertTrue("--no-playlist" in mp3); assertTrue("--restrict-filenames" in mp3)
        val mp4 = YtdlArgs.options("mp4", d).toMap()
        assertEquals("bestvideo+bestaudio/best", mp4["-f"]); assertEquals("mp4", mp4["--merge-output-format"])
        assertEquals(File(d, "%(title)s.%(ext)s").path, mp4["-o"])
    }

    @Test fun urlValidation() {
        assertEquals("https://x.org/v?id=1", YtdlArgs.validateUrl(" https://x.org/v?id=1 "))
        for (bad in listOf("", "ftp://x", "file:///etc/passwd", "javascript:alert(1)", "--exec rm"))
            assertThrows(IllegalArgumentException::class.java) { YtdlArgs.validateUrl(bad) }
    }

    @Test fun finalPathIgnoresProgressAndOutsideFiles() {
        val d = dir(); val inside = File(d, "a.mp4").apply { writeText("x") }
        val outside = Files.createTempFile("o", ".mp4").toFile()
        assertEquals(inside, YtdlArgs.finalPath("[download] 100%\n${inside.path}\n", d))
        assertNull(YtdlArgs.finalPath("${outside.path}\n", d))
        assertNull(YtdlArgs.finalPath("[download] 100%\n", d))
    }

    @Test fun downloadAudioAndVideoIndexed() {
        val d = dir(); val eng = FakeEngine()
        val m = MediaDownloader(eng, MediaIndex(File(d, "index.json")), File(d, "media"))
        val progress = mutableListOf<Float>()
        val a = m.download("https://example.org/watch?v=1", "mp3") { p, _ -> progress += p }
        assertEquals("audio", a.type); assertTrue(a.path.endsWith(".mp3")); assertEquals("My Clip", a.title)
        assertEquals(listOf(50f, 100f), progress)
        val v = m.download("https://example.org/watch?v=1", "MP4")
        assertEquals("video", v.type); assertTrue(v.path.endsWith(".mp4"))
        assertEquals(1, eng.inits) // engine unpacked once
        assertEquals(2, m.index.list().size)
        // Re-downloading the same file replaces its entry.
        m.download("https://example.org/watch?v=1", "mp4"); assertEquals(2, m.index.list().size)
        assertTrue(m.index.remove(v.id)); assertFalse(File(v.path).exists()); assertEquals(1, m.index.list().size)
        File(a.path).delete(); assertTrue(m.index.prune().isEmpty())
        assertEquals("2025.11.12", m.version())
    }

    @Test fun engineErrorsSurface() {
        val d = dir()
        val m = MediaDownloader(FakeEngine("ERROR: Unsupported URL"), MediaIndex(File(d, "i.json")), d)
        val e = assertThrows(IllegalStateException::class.java) { m.download("https://example.org/x") }
        assertEquals("ERROR: Unsupported URL", e.message)
        assertTrue(m.index.list().isEmpty())
    }

    @Test fun mediaToolGating() = runBlocking {
        val d = dir()
        val m = MediaDownloader(FakeEngine(), MediaIndex(File(d, "i.json")), d)
        val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
        val reg = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "nomedia", capabilities = listOf("memory"))))
        val tools = MediaTools(reg, { m })
        assertTrue(tools.run(ToolCall("download_media", mapOf("url" to "https://example.org/v", "format" to "mp3"))).startsWith("Downloaded audio"))
        assertTrue(tools.run(ToolCall("download_media", mapOf("url" to "nope"))).startsWith("(download error"))
        reg.activeId = "nomedia"
        assertEquals("(tool not permitted: download_media)", tools.run(ToolCall("download_media", mapOf("url" to "https://x.org"))))
    }
}
