// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC.
package org.kairos.agent

import android.app.Application
import org.kairos.agent.agent.AgentMemory
import org.kairos.agent.agent.CharacterRegistry
import org.kairos.agent.agent.ChatBackend
import org.kairos.agent.agent.Engine
import org.kairos.agent.data.MemoryStore
import org.kairos.agent.data.SecureStore
import org.kairos.agent.data.Settings
import org.kairos.agent.llm.ChatMessage
import org.kairos.agent.llm.LlmClient

class KairosApp : Application() {
    lateinit var settings: Settings
    lateinit var secrets: SecureStore
    lateinit var store: MemoryStore
    lateinit var characters: CharacterRegistry
    val llm = LlmClient()
    lateinit var engine: Engine

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        secrets = SecureStore(this)
        store = MemoryStore(this)
        characters = CharacterRegistry(
            CharacterRegistry.parsePack(assets.open("characters.json").bufferedReader().readText())
        ).also { it.activeId = settings.activeCharacter }
        val mem = object : AgentMemory {
            override fun history(limit: Int) = store.recentMessages(limit).map { ChatMessage(it.role, it.content) }
            override fun append(role: String, content: String) { store.addMessage(role, content) }
            override fun remember(content: String) = store.remember(content)
            override fun recall(query: String, limit: Int) = store.recall(query, limit).map { it.content }
        }
        val backend = ChatBackend { messages, onDelta ->
            val pid = settings.activeProvider
            llm.chat(settings.apiUrl(pid), secrets.get(SecureStore.apiKeyName(pid)).orEmpty(),
                settings.model(pid), messages, onDelta = onDelta).text
        }
        engine = Engine(characters, mem, backend)
    }
}
