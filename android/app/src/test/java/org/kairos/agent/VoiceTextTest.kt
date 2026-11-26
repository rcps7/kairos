// SPDX-License-Identifier: GPL-3.0-or-later
// Spoken-reply text cleanup and the voice level meter mapping.
package org.kairos.agent

import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.voice.VoiceText
import org.kairos.agent.voice.VoskModels
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class VoiceTextTest {
    @Test fun stripsMarkdownCodeAndLinks() {
        val s = VoiceText.forSpeech("""
            # Title
            Here is **bold** and `inline` text.
            ```kotlin
            val x = 1
            ```
            - item one
            See [the docs](https://example.org/docs) or https://x.org/y.
            <tool name="web_search">{"query":"x"}</tool>
        """.trimIndent())
        assertFalse(s.contains("**")); assertFalse(s.contains("val x")); assertFalse(s.contains("https://"))
        assertFalse(s.contains("<tool")); assertFalse(s.contains("#"))
        assertTrue(s.contains("Title")); assertTrue(s.contains("bold and inline text"))
        assertTrue(s.contains("(code omitted)")); assertTrue(s.contains("item one")); assertTrue(s.contains("the docs"))
    }

    @Test fun longRepliesAreCut() {
        val s = VoiceText.forSpeech("word ".repeat(2000), maxChars = 100)
        assertTrue(s.length <= 101); assertTrue(s.endsWith("…"))
    }

    @Test fun levelIsClamped() {
        assertEquals(0f, VoiceText.level(-10f), 0f)
        assertEquals(1f, VoiceText.level(50f), 0f)
        assertEquals(0.5f, VoiceText.level(4f), 0.001f)
    }

    private fun zip(vararg entries: String): ByteArray = ByteArrayOutputStream().also { bo ->
        ZipOutputStream(bo).use { z -> entries.forEach { e -> z.putNextEntry(ZipEntry(e)); if (!e.endsWith("/")) z.write("x".toByteArray()); z.closeEntry() } }
    }.toByteArray()

    @Test fun voskJsonParsing() {
        assertEquals("hello world", VoskModels.text("""{"partial" : "hello world"}"""))
        assertEquals("turn on the light", VoskModels.text("""{"text" : "turn on the light"}"""))
        assertEquals("", VoskModels.text("not json")); assertEquals("", VoskModels.text(null))
    }

    @Test fun voskModelUnzip() {
        val dest = File(Files.createTempDirectory("vosk").toFile(), "model")
        val root = VoskModels.unzipModel(zip("vosk-model-small/", "vosk-model-small/am/final.mdl", "vosk-model-small/conf/model.conf").inputStream(), dest)
        assertEquals("vosk-model-small", root.name)
        assertEquals(root.canonicalFile, VoskModels.installed(dest.parentFile)?.canonicalFile)
        assertThrows(IllegalStateException::class.java) { VoskModels.unzipModel(zip("readme.txt").inputStream(), dest) }
    }

    @Test fun voskZipSlipRejected() {
        val dest = File(Files.createTempDirectory("vosk").toFile(), "model")
        assertThrows(SecurityException::class.java) { VoskModels.unzipModel(zip("../evil.txt").inputStream(), dest) }
        assertFalse(File(dest.parentFile, "evil.txt").exists())
    }

    @Test fun voskModelUrlMustBeHttps() {
        assertThrows(IllegalArgumentException::class.java) { VoskModels.download("http://x.org/m.zip", Files.createTempDirectory("v").toFile()) }
    }
}
