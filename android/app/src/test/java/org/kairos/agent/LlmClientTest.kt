// SPDX-License-Identifier: GPL-3.0-or-later
package org.kairos.agent

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.llm.ChatMessage
import org.kairos.agent.llm.LlmClient
import org.kairos.agent.llm.LlmException

class LlmClientTest {
    private val c = LlmClient()

    @Test fun parseModelsShapes() {
        assertEquals(listOf("a", "b"), c.parseModels("""{"data":[{"id":"b"},{"id":"a"},{"id":"a"}]}"""))
        assertEquals(listOf("m1"), c.parseModels("""{"models":[{"name":"m1"}]}"""))
        assertEquals(listOf("x", "y"), c.parseModels("""["y","x"]"""))
    }

    @Test fun parseSse() {
        assertEquals("Hi", c.parseSseLine("""data: {"choices":[{"delta":{"content":"Hi"}}]}"""))
        assertEquals(LlmClient.DONE, c.parseSseLine("data: [DONE]"))
        assertNull(c.parseSseLine(": keep-alive"))
    }

    @Test fun chatNonStreamingAgainstServer() = runTest {
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setBody("""{"choices":[{"message":{"content":"pong"}}],"usage":{"prompt_tokens":3,"completion_tokens":1}}"""))
            s.start()
            val r = c.chat(s.url("/v1/chat/completions").toString(), "k", "m", listOf(ChatMessage("user", "ping")))
            assertEquals("pong", r.text)
            assertEquals(1, r.usage?.completionTokens)
            val req = s.takeRequest()
            assertEquals("Bearer k", req.getHeader("Authorization"))
            assertTrue(req.body.readUtf8().contains("\"model\":\"m\""))
        }
    }

    @Test fun chatStreaming() = runTest {
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody(
                "data: {\"choices\":[{\"delta\":{\"content\":\"po\"}}]}\n\n" +
                    "data: {\"choices\":[{\"delta\":{\"content\":\"ng\"}}]}\n\ndata: [DONE]\n\n"))
            s.start()
            val parts = mutableListOf<String>()
            val r = c.chat(s.url("/chat/completions").toString(), "k", "m", listOf(ChatMessage("user", "ping"))) { parts += it }
            assertEquals("pong", r.text); assertEquals(listOf("po", "ng"), parts)
        }
    }

    @Test fun missingKeyRaises() = runTest {
        try { c.chat("https://x/chat/completions", "", "m", emptyList()); fail() } catch (e: LlmException) { }
    }

    @Test fun listModelsUsesDerivedUrl() = runTest {
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setBody("""{"data":[{"id":"z"}]}""")); s.start()
            assertEquals(listOf("z"), c.listModels(s.url("/v1/chat/completions").toString(), "k"))
            assertEquals("/v1/models", s.takeRequest().path)
        }
    }
}
