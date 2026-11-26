// SPDX-License-Identifier: GPL-3.0-or-later
// Spoken-reply text cleanup and the voice level meter mapping.
package org.kairos.agent

import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.voice.VoiceText

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
}
