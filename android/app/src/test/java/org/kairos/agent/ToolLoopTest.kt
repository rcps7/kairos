// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_stream_tools.py (stream_* cases) plus capability gates and learn_web -> library.
package org.kairos.agent

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.llm.ChatMessage
import org.kairos.agent.web.Page
import org.kairos.agent.web.SearchResult
import java.io.File

class ToolLoopTest {
    private val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
    private val docs = mutableListOf<String>()
    private val lib = object : Library {
        override fun add(url: String, title: String, html: String, text: String, summary: String): String { docs += "$url|$summary"; return "id${docs.size}" }
    }
    private fun web(reg: CharacterRegistry) = WebTools(reg,
        search = { q, _ -> listOf(SearchResult("R for $q", "https://r.example", "desc")) },
        fetch = { u -> Page("Title of $u", "page text", "<p>page text</p>") },
        summarize = { "• summary" }, library = lib)

    /** Backend that streams the given pieces on the first call and returns `final` afterwards. */
    private fun backend(pieces: List<String>, final: String = "FINAL ANSWER", seen: MutableList<List<ChatMessage>> = mutableListOf()) =
        ChatBackend { msgs, onDelta ->
            seen += msgs
            if (seen.size == 1) { pieces.forEach { onDelta?.invoke(it) }; pieces.joinToString("") } else final
        }

    private suspend fun stream(e: Engine, q: String = "q"): String { val sb = StringBuilder(); e.chat(q) { sb.append(it) }; return sb.toString() }

    @Test fun streamExecutesToolRequest() = runTest {
        val reg = CharacterRegistry(pack); val seen = mutableListOf<List<ChatMessage>>()
        val e = Engine(reg, FakeMemory(), backend(listOf("Let me look that up.", "<web_search><query>x</query></web_search>"), seen = seen), tools = web(reg))
        val out = stream(e)
        assertFalse(out.contains("<web_search")); assertTrue(out.contains("FINAL ANSWER"))
        val fed = seen[1].last().content
        assertTrue(fed.contains("TOOL RESULTS")); assertTrue(fed.contains("<<UNTRUSTED web_search")); assertTrue(fed.contains("R for x"))
    }

    @Test fun streamPlainReplyPassthrough() = runTest {
        val reg = CharacterRegistry(pack)
        assertEquals("Hello world", stream(Engine(reg, FakeMemory(), backend(listOf("Hello", " world")), tools = web(reg))))
    }

    @Test fun streamFunctionFormTool() = runTest {
        val reg = CharacterRegistry(pack)
        val out = stream(Engine(reg, FakeMemory(), backend(listOf("", "web_search(\"cats\")")), tools = web(reg)))
        assertFalse(out.contains("web_search(")); assertTrue(out.contains("FINAL ANSWER"))
    }

    @Test fun learnWebSavesToLibrary() = runTest {
        val reg = CharacterRegistry(pack)
        val reply = Engine(reg, FakeMemory(), backend(emptyList()), tools = web(reg)).chat("/learn https://a.example/doc")
        assertTrue(reply.contains("Title of https://a.example/doc")); assertTrue(reply.contains("• summary"))
        assertEquals(listOf("https://a.example/doc|• summary"), docs)
    }

    @Test fun capabilityGateBlocksTools() = runTest {
        val reg = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "mem", capabilities = listOf("memory"))))
        reg.activeId = "mem"
        val t = web(reg)
        assertTrue(t.run(ToolCall("web_search", mapOf("query" to "x"))).startsWith("(tool not permitted"))
        assertTrue(t.run(ToolCall("learn_web", mapOf("url" to "https://a"))).startsWith("(tool not permitted"))
        assertTrue(docs.isEmpty())
    }

    @Test fun systemPromptCarriesProtocolAndGuardrail() {
        val reg = CharacterRegistry(pack)
        val sp = Engine(reg, FakeMemory(), backend(emptyList()), tools = web(reg)).systemPrompt("hi")
        assertTrue(sp.contains("TOOL PROTOCOL")); assertTrue(sp.contains("UNTRUSTED"))
    }
}
