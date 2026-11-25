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

    /** End-to-end: the app chats with a configured (local, OpenAI-compatible) LLM provider. */
    @Test fun chatsWithConfiguredProvider() {
        val server = ServerSocket(0)
        thread(isDaemon = true) {
            server.accept().use { sock ->
                val inp = sock.getInputStream().bufferedReader()
                var len = 0
                while (true) {
                    val l = inp.readLine() ?: break
                    if (l.isEmpty()) break
                    if (l.lowercase().startsWith("content-length:")) len = l.substringAfter(':').trim().toInt()
                }
                repeat(len) { inp.read() }
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
        compose.waitUntil(15_000) { compose.onAllNodesWithText("KAIROS_PONG").fetchSemanticsNodes().isNotEmpty() }
        server.close()
    }
}
