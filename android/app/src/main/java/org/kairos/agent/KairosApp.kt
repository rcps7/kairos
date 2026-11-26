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
import org.kairos.agent.agent.Agent
import org.kairos.agent.agent.PlanTools
import org.kairos.agent.jobs.JobQueue
import org.kairos.agent.agent.EmailTools
import org.kairos.agent.email.EmailClient
import org.kairos.agent.email.EmailConfig
import org.kairos.agent.email.MailItem
import org.kairos.agent.llm.Providers
import org.kairos.agent.telegram.BotHost
import org.kairos.agent.telegram.TelegramService
import kotlinx.coroutines.CompletableDeferred
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
    val jobs = JobQueue()
    lateinit var agent: Agent
    lateinit var email: EmailClient
    lateinit var botHost: BotHost

    fun emailConfig() = EmailConfig(settings.emailAddress, secrets.get(SecureStore.EMAIL_PASSWORD).orEmpty(),
        settings.imapHost, settings.imapPort, settings.smtpHost, settings.smtpPort)

    /** Run work through the FIFO job queue and wait for its result (keeps app and bot turns ordered). */
    suspend fun <T> queued(label: String, block: suspend () -> T): T {
        val d = CompletableDeferred<T>()
        jobs.submit(org.kairos.agent.jobs.Job(label = label,
            onError = { _, e -> d.completeExceptionally(e) }) { _, _ -> d.complete(block()) })
        return d.await()
    }

    /** Kill switch (desktop emergency_kill): stop background services and end the process. */
    fun emergencyKill() {
        runCatching { TelegramService.stop(this) }
        runCatching { stopService(android.content.Intent(this, KairosJobService::class.java)) }
        android.os.Process.killProcess(android.os.Process.myPid())
    }

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
            fallback = PlanTools(store, EmailTools(characters, EmailClient { emailConfig() })),
        )
        email = EmailClient { emailConfig() }
        engine = Engine(characters, mem, backend, tools = webTools)
        agent = Agent(engine, backend, store, mem)
        KairosJobService.observe(this, jobs)
        botHost = AppBotHost(this)
        if (settings.telegramEnabled) runCatching { TelegramService.start(this) }
    }
}


/** Connects the Telegram bot to the app's engine, stores and settings. */
class AppBotHost(private val app: KairosApp) : BotHost {
    override fun allowedUserIds() = Settings.parseAllowedIds(app.settings.telegramAllowed)
    override fun can(capability: String) = app.characters.can(capability)
    override fun activeCharacterName() = app.characters.active().name
    override fun characters() = app.characters.all.map { Triple(it.id, it.name, it.description) }
    override fun activeCharacterId() = app.characters.activeId
    override fun setCharacter(id: String): String? {
        val c = app.characters.get(id) ?: return null
        app.characters.activeId = c.id; app.settings.activeCharacter = c.id; return c.name
    }
    override suspend fun chat(prompt: String, onDelta: (String) -> Unit) = app.queued("telegram") { app.engine.chat(prompt, onDelta) }
    override suspend fun search(query: String) = app.searcher.search(query, 10).map { Triple(it.title, it.url, it.description) }
    override suspend fun learn(url: String) = app.webTools.learn(url).let { it.title to it.summary }
    override suspend fun readMail(limit: Int): List<MailItem> = app.email.readMail(limit)
    override suspend fun sendMail(to: String, subject: String, body: String) { app.email.sendMail(to, subject, body) }
    override fun remember(content: String) = app.store.remember(content)
    override fun memories() = app.store.allMemories().map { it.content }
    override fun providers() = Providers.PRESETS.map { it.id to app.settings.model(it.id) }
    override fun activeProvider() = app.settings.activeProvider
    override fun setProvider(id: String): Boolean {
        if (Providers.byId(id) == null) return false
        app.settings.activeProvider = id; return true
    }
    override fun plans() = app.store.list(20)
    override fun plan(id: String) = app.store.get(id)
    override fun newPlan(goal: String) = app.store.create(goal, emptyList())
    override fun mode() = app.settings.agentMode
    override fun setMode(mode: String): String {
        val m = mode.lowercase().takeIf { it in setOf("chat", "plan", "execute") } ?: "chat"
        app.settings.agentMode = m; return m
    }
    override suspend fun runAgent(goal: String, mode: String) = app.queued("telegram-agent") { app.agent.run(goal, mode).text }
    override fun kill() = app.emergencyKill()
}
