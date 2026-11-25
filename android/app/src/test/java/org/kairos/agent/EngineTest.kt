// SPDX-License-Identifier: GPL-3.0-or-later
package org.kairos.agent

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.llm.ChatMessage
import java.io.File

class FakeMemory : AgentMemory {
    val log = mutableListOf<ChatMessage>(); val mem = linkedSetOf<String>()
    override fun history(limit: Int) = log.takeLast(limit)
    override fun append(role: String, content: String) { log += ChatMessage(role, content) }
    override fun remember(content: String) = mem.add(content)
    override fun recall(query: String, limit: Int) = mem.filter { m -> query.lowercase().split(" ").any { it.length > 2 && m.lowercase().contains(it) } }.take(limit)
}

class EngineTest {
    private val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())

    @Test fun rememberThenRecallFeedsSystemPrompt() = runTest {
        val m = FakeMemory(); var seen: List<ChatMessage> = emptyList()
        val e = Engine(CharacterRegistry(pack), m, ChatBackend { msgs, _ -> seen = msgs; "ok" })
        assertEquals("Saved to memory.", e.chat("/remember My ESP32 is on COM5"))
        assertEquals("ok", e.chat("Which port is my esp32 on?"))
        assertTrue(seen.first().content.contains("My ESP32 is on COM5"))
        assertEquals("user", seen.last().role)
        assertEquals(4, m.log.size)
    }

    @Test fun memoryCapabilityIsEnforced() = runTest {
        val r = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "nomem", capabilities = listOf("web_search"))))
        r.activeId = "nomem"
        val e = Engine(r, FakeMemory(), ChatBackend { _, _ -> "x" })
        assertTrue(e.chat("/remember secret").contains("does not have"))
    }

    @Test fun historyIsSentInOrder() = runTest {
        val m = FakeMemory(); var seen: List<ChatMessage> = emptyList()
        val e = Engine(CharacterRegistry(pack), m, ChatBackend { msgs, _ -> seen = msgs; "a${seen.size}" })
        e.chat("one"); e.chat("two")
        assertEquals(listOf("system", "user", "assistant", "user"), seen.map { it.role })
    }
}
