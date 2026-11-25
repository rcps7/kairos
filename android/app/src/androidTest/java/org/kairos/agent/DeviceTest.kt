// SPDX-License-Identifier: GPL-3.0-or-later
// Instrumented tests: run on an Android 10+ emulator in CI.
package org.kairos.agent

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.kairos.agent.data.MemoryStore
import org.kairos.agent.data.SecureStore
import org.kairos.agent.ui.MainActivity
import java.net.ServerSocket
import kotlin.concurrent.thread

@RunWith(AndroidJUnit4::class)
class DeviceTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    private val ctx get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun secureStoreRoundTripAndCiphertextOnDisk() {
        val s = SecureStore(ctx)
        s.put("t", "sk-test-123")
        assertEquals("sk-test-123", s.get("t"))
        val raw = ctx.getSharedPreferences("kairos_secrets", 0).getString("t", "")!!
        assertFalse(raw.contains("sk-test-123"))
        s.put("t", null); assertNull(s.get("t"))
    }

    @Test fun memoryStoreRememberRecallForget() {
        val m = MemoryStore(ctx, null) // in-memory database
        assertTrue(m.remember("ESP32 lives on the bench"))
        assertFalse(m.remember("ESP32 lives on the bench"))
        assertEquals(1, m.recall("where is the esp32").size)
        m.forget(m.allMemories().first().id)
        assertTrue(m.allMemories().isEmpty())
    }

    @Test fun libraryAddSearchDelete() {
        val m = MemoryStore(ctx, null)
        val id = m.addDocument("https://a.example", "Resistor colour codes", "<p>x</p>", "Brown black red is 1k", "• 1k = brown black red")
        assertEquals(1, m.searchDocuments("brown black").size)
        assertEquals(0, m.searchDocuments("capacitor").size)
        assertEquals("Resistor colour codes", m.allDocuments().single().title)
        m.deleteDocument(id); assertTrue(m.allDocuments().isEmpty())
    }

    /** The Library tab is reachable from the bottom bar. */
    @Test fun libraryTabOpens() {
        compose.onNodeWithTag("tab_Library").performClick()
        compose.onNodeWithTag("learn_url").assertIsDisplayed()
    }

    /** End-to-end: the app chats with a configured (local, OpenAI-compatible) LLM provider. */
    @Test fun chatsWithConfiguredProvider() {
        val server = ServerSocket(0)
        thread(isDaemon = true) {
            server.accept().use { sock ->
                // Read headers and body as raw bytes: Content-Length counts bytes, and the
                // system prompt can contain multi-byte UTF-8 characters.
                val inp = sock.getInputStream()
                val head = java.io.ByteArrayOutputStream()
                while (!head.toString("ISO-8859-1").endsWith("\r\n\r\n")) {
                    val b = inp.read(); if (b < 0) break; head.write(b)
                }
                val len = head.toString("ISO-8859-1").lines()
                    .firstOrNull { it.lowercase().startsWith("content-length:") }
                    ?.substringAfter(':')?.trim()?.toInt() ?: 0
                var got = 0
                val buf = ByteArray(8192)
                while (got < len) { val n = inp.read(buf, 0, minOf(buf.size, len - got)); if (n < 0) break; got += n }
                val body = """{"choices":[{"message":{"content":"KAIROS_PONG"}}]}"""
                sock.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" +
                    "Content-Length: ${body.length}\r\nConnection: close\r\n\r\n$body").toByteArray())
            }
        }
        val app = ctx.applicationContext as KairosApp
        app.settings.setApiUrl("custom", "http://127.0.0.1:${server.localPort}/v1/chat/completions")
        app.settings.setModel("custom", "test-model")
        app.secrets.put(SecureStore.apiKeyName("custom"), "test-key")
        app.settings.activeProvider = "custom"
        app.store.clearMessages()

        compose.onNodeWithTag("input").performTextInput("ping")
        compose.onNodeWithTag("send").performClick()
        try {
            compose.waitUntil(30_000) { compose.onAllNodesWithText("KAIROS_PONG", substring = true).fetchSemanticsNodes().isNotEmpty() }
        } catch (e: Throwable) {
            val stored = app.store.recentMessages(10).joinToString(" | ") { "${it.role}: ${it.content.take(200)}" }
            val shown = compose.onAllNodes(hasText("", substring = true)).fetchSemanticsNodes()
                .joinToString(" | ") { n -> n.config.getOrElseNullable(androidx.compose.ui.semantics.SemanticsProperties.Text) { null }?.joinToString() ?: "" }
            throw AssertionError("No reply. stored=[$stored] shown=[${shown.take(1500)}]", e)
        }
        server.close()
    }
}
