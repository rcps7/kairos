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
import org.kairos.agent.agent.Library
import org.kairos.agent.agent.WebTools
import org.kairos.agent.web.WebScraper
import org.kairos.agent.web.WebSearcher

class KairosApp : Application() {
    lateinit var settings: Settings
    lateinit var secrets: SecureStore
    lateinit var store: MemoryStore
    lateinit var characters: CharacterRegistry
    val llm = LlmClient()
    lateinit var engine: Engine
    lateinit var webTools: WebTools
    val searcher = WebSearcher()
    val scraper = WebScraper()

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
        webTools = WebTools(
            characters,
            search = { q, n -> searcher.search(q, n) },
            fetch = { u -> scraper.fetch(u) },
            summarize = { prompt -> backend.complete(listOf(ChatMessage("user", prompt)), null) },
            library = object : Library {
                override fun add(url: String, title: String, html: String, text: String, summary: String) =
                    store.addDocument(url, title, html, text, summary)
            },
        )
        engine = Engine(characters, mem, backend, tools = webTools)
    }
}
