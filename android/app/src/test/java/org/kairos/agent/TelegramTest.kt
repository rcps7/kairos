// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_telegram_auth.py (allowlist) plus the bot's commands against a mock Bot API.
package org.kairos.agent

import kotlinx.coroutines.*
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.kairos.agent.agent.InMemoryPlanStore
import org.kairos.agent.agent.Plan
import org.kairos.agent.data.Settings
import org.kairos.agent.email.MailItem
import org.kairos.agent.telegram.*
import java.util.Collections

class FakeHost(var allowed: Set<Long> = setOf(111L), var caps: Set<String>? = null) : BotHost {
    val plansStore = InMemoryPlanStore()
    val sent = mutableListOf<Triple<String, String, String>>()
    val remembered = mutableListOf<String>()
    var killed = false
    var mode = "chat"
    var character = "general"
    var provider = "moonshot"
    override fun allowedUserIds() = allowed
    override fun can(capability: String) = caps?.contains(capability) ?: true
    override fun activeCharacterName() = if (character == "general") "General" else "Law Assist"
    override fun characters() = listOf(Triple("general", "General", ""), Triple("law_assist", "Law Assist", ""))
    override fun activeCharacterId() = character
    override fun setCharacter(id: String) = characters().firstOrNull { it.first == id }?.let { character = id; it.second }
    override suspend fun chat(prompt: String, onDelta: (String) -> Unit): String { onDelta("Hel"); onDelta("lo"); return "Hello: $prompt" }
    override suspend fun search(query: String) = listOf(Triple("Kotlin", "https://kotlinlang.org", "Docs"))
    override suspend fun learn(url: String) = "Title" to "• point"
    override suspend fun readMail(limit: Int) = listOf(MailItem("a@b", "Hi", "today", "body text"))
    override suspend fun sendMail(to: String, subject: String, body: String) { sent += Triple(to, subject, body) }
    override fun remember(content: String) = remembered.add(content)
    override fun memories() = remembered.toList()
    override fun providers() = listOf("moonshot" to "kimi", "openai" to "gpt")
    override fun activeProvider() = provider
    override fun setProvider(id: String) = (id in setOf("moonshot", "openai")).also { if (it) provider = id }
    override fun plans(): List<Plan> = plansStore.list()
    override fun plan(id: String) = plansStore.get(id)
    override fun newPlan(goal: String) = plansStore.create(goal)
    override fun mode() = mode
    override fun setMode(mode: String) = (mode.takeIf { it in setOf("chat", "plan", "execute") } ?: "chat").also { this.mode = it }
    override suspend fun runAgent(goal: String, mode: String) = "[$mode] $goal done"
    override fun kill() { killed = true }
    val skillsMap = mutableMapOf("hello" to "says hi")
    override fun skills() = skillsMap.toList()
    override suspend fun runSkill(name: String, args: Map<String, String>) =
        if (name in skillsMap) "ran $name $args" else throw IllegalStateException("Skill '$name' not found.")
    override suspend fun generateSkill(name: String, description: String) = "// name: $name\nfunction run(){return 1}"
    override fun createSkill(name: String, code: String): String { skillsMap[name] = "new"; return "$name.js" }
    override suspend fun git(sub: String, rest: String) = "git:$sub:$rest"
    override suspend fun downloadMedia(url: String, fmt: String) =
        if (url.startsWith("https://")) "Clip ($fmt)" to "/media/clip.$fmt" else throw IllegalArgumentException("Enter an http(s) URL.")
}

class TelegramTest {
    private lateinit var server: MockWebServer
    private val calls = Collections.synchronizedList(mutableListOf<Pair<String, JsonObject>>())
    @Volatile private var updatesJson = "[]"
    @Volatile private var getUpdatesCode = 200

    @Before fun up() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val method = request.path!!.substringAfterLast('/')
                val body = request.body.readUtf8()
                calls += method to (if (body.isBlank()) JsonObject(emptyMap()) else Json.parseToJsonElement(body).jsonObject)
                return when (method) {
                    "getUpdates" -> if (getUpdatesCode != 200) MockResponse().setResponseCode(getUpdatesCode).setBody("{\"ok\":false,\"description\":\"Unauthorized\"}")
                        else { val u = updatesJson; updatesJson = "[]"; MockResponse().setBody("{\"ok\":true,\"result\":$u}") }
                    "sendMessage" -> MockResponse().setBody("{\"ok\":true,\"result\":{\"message_id\":${calls.size}}}")
                    else -> MockResponse().setBody("{\"ok\":true,\"result\":true}")
                }
            }
        }
        server.start()
    }

    @After fun down() { server.shutdown() }

    private fun api() = TelegramApi("123456:" + "A".repeat(35), server.url("/").toString().trimEnd('/'))
    private fun msg(uid: Long, text: String, id: Long = 1) = TgUpdate(id, uid, uid, text, 10)
    private fun texts(method: String = "sendMessage") = calls.filter { it.first == method }.map { it.second["text"]!!.jsonPrimitive.content }

    @Test fun allowlist() {
        assertEquals(setOf(111L, 222L), Settings.parseAllowedIds("111, 222, nope"))
        val bot = TelegramBot(api(), FakeHost(Settings.parseAllowedIds("111,222")))
        assertTrue(bot.authorized(111)); assertTrue(bot.authorized(222)); assertFalse(bot.authorized(999)); assertFalse(bot.authorized(null))
    }

    @Test fun emptyAllowlistDeniesAll() = runTest {
        val bot = TelegramBot(api(), FakeHost(Settings.parseAllowedIds("")))
        assertFalse(bot.authorized(111))
        bot.handle(msg(111, "/chat hi"))
        assertTrue(texts().single().startsWith("Unauthorized."))
        bot.handle(msg(111, "/whoami"))
        assertTrue(texts().last().contains("111"))
    }

    @Test fun tokenFormat() {
        assertTrue(validateTokenFormat("123456789:" + "a".repeat(35)))
        assertFalse(validateTokenFormat("12345:short")); assertFalse(validateTokenFormat(""))
    }

    @Test fun chatStreamsThenFinalizes() = runTest {
        val bot = TelegramBot(api(), FakeHost(), editIntervalMs = 10)
        bot.handle(msg(111, "/chat@kairos_bot ping"))
        assertEquals("…", texts().first())
        assertEquals("Hello: ping", texts("editMessageText").last())
    }

    @Test fun commandsRouteToHost() = runTest {
        val h = FakeHost(); val bot = TelegramBot(api(), h)
        bot.handle(msg(111, "/search kotlin")); assertTrue(texts().last().startsWith("Results for 'kotlin':\n1. Kotlin\nhttps://kotlinlang.org"))
        bot.handle(msg(111, "/learn https://x.org")); assertEquals("Learned from: Title\n\n• point", texts().last())
        bot.handle(msg(111, "/mail")); assertTrue(texts().last().contains("Subject: Hi"))
        bot.handle(msg(111, "/sendmail bob@x.org Hello there | Body here")); assertEquals("Email sent.", texts().last())
        assertEquals(Triple("bob@x.org", "Hello there", "Body here"), h.sent.single())
        bot.handle(msg(111, "/remember the lab code is 42")); assertEquals("Saved to retention.", texts().last())
        bot.handle(msg(111, "/memory")); assertTrue(texts().last().contains("lab code"))
        bot.handle(msg(111, "/setllm openai")); assertEquals("Active LLM set to openai", texts().last())
        bot.handle(msg(111, "/setllm nope")); assertEquals("Provider 'nope' not found.", texts().last())
        bot.handle(msg(111, "/setcharacter law_assist")); assertEquals("Now operating as: Law Assist", texts().last())
        bot.handle(msg(111, "/mode execute")); assertEquals("Mode set to 'execute'.", texts().last())
        bot.handle(msg(111, "/newplan Build a robot")); val pid = texts().last().removePrefix("Plan created: ")
        bot.handle(msg(111, "/plan $pid")); assertEquals("Build a robot [open]", texts().last())
        bot.handle(msg(111, "/execute ship it")); assertEquals("[execute] ship it done", texts().last())
        bot.handle(msg(111, "/git commit")); assertEquals("Usage: /git commit <message>", texts().last())
        bot.handle(msg(111, "/git commit fix bug")); assertEquals("git:commit:fix bug", texts().last())
        bot.handle(msg(111, "/image x")); assertTrue(texts().last().contains("not available in the Android app yet"))
        bot.handle(msg(111, "hello without slash")); assertTrue(texts().last().contains("not available")) // ignored: no new message
    }

    @Test fun downloadAsksForFormat() = runTest {
        val h = FakeHost(); val bot = TelegramBot(api(), h)
        bot.handle(msg(111, "/download")); assertEquals("Usage: /download <url>", texts().last())
        bot.handle(msg(111, "/download https://example.org/v"))
        assertEquals("Select format:", texts().last())
        assertTrue(calls.last().second.toString().contains("dl_mp3"))
        bot.handle(TgUpdate(20, 111, 111, null, 10, "cb", "dl_mp3"))
        assertEquals("Downloaded: Clip (mp3)\nSaved to: /media/clip.mp3", texts("editMessageText").last())
        bot.handle(TgUpdate(21, 111, 111, null, 10, "cb", "dl_mp4"))
        assertEquals("No pending URL found.", texts("editMessageText").last())
        bot.handle(msg(111, "/download ftp://x")); bot.handle(TgUpdate(22, 111, 111, null, 10, "cb", "dl_mp4"))
        assertEquals("Download error: Enter an http(s) URL.", texts("editMessageText").last())
    }

    @Test fun skillCommandsWithApproval() = runTest {
        val h = FakeHost(); val bot = TelegramBot(api(), h)
        bot.handle(msg(111, "/skills")); assertEquals("Skills:\n- hello: says hi", texts().last())
        bot.handle(msg(111, "/runs hello a=1 b=2")); assertEquals("Result:\nran hello {a=1, b=2}", texts().last())
        bot.handle(msg(111, "/runs ghost")); assertTrue(texts().last().startsWith("Skill error"))
        bot.handle(msg(111, "/newskill Bad/Name x")); assertTrue(texts().last().startsWith("Invalid name"))
        bot.handle(msg(111, "/newskill weather get the weather"))
        assertTrue(texts().last().startsWith("Proposed skill 'weather'"))
        assertFalse("weather" in h.skillsMap) // nothing saved before approval
        bot.handle(TgUpdate(9, 111, 111, null, 10, "cb", "approve_skill"))
        assertEquals("Skill 'weather' created.", texts("editMessageText").last())
        assertTrue("weather" in h.skillsMap)
        bot.handle(TgUpdate(10, 111, 111, null, 10, "cb", "approve_skill"))
        assertEquals("No pending skill.", texts("editMessageText").last())
    }

    @Test fun capabilityDenied() = runTest {
        val bot = TelegramBot(api(), FakeHost(caps = setOf("memory")))
        bot.handle(msg(111, "/search x")); assertTrue(texts().last().contains("not permitted"))
        bot.handle(msg(111, "/sendmail a@b s | b")); assertTrue(texts().last().contains("email send"))
    }

    @Test fun killAsksThenConfirms() = runTest {
        val h = FakeHost(); val bot = TelegramBot(api(), h)
        bot.handle(msg(111, "/kill"))
        val kb = calls.last { it.first == "sendMessage" }.second["reply_markup"]!!.jsonObject["inline_keyboard"]!!.jsonArray[0].jsonArray
        assertEquals(listOf("confirm_kill", "cancel_kill"), kb.map { it.jsonObject["callback_data"]!!.jsonPrimitive.content })
        assertFalse(h.killed)
        bot.handle(TgUpdate(2, 999, 999, null, 10, "cb1", "confirm_kill"))
        assertFalse(h.killed) // unauthorized user cannot press it
        bot.handle(TgUpdate(3, 111, 111, null, 10, "cb2", "confirm_kill"))
        assertTrue(h.killed)
    }

    @Test fun pollingDispatchesUpdatesAndStopsOnBadToken() = runBlocking {
        updatesJson = """[{"update_id":5,"message":{"message_id":1,"from":{"id":111},"chat":{"id":111},"text":"/whoami"}},
            {"update_id":6,"callback_query":{"id":"q","from":{"id":111},"data":"cancel_kill","message":{"message_id":3,"chat":{"id":111}}}}]"""
        val bot = TelegramBot(api(), FakeHost())
        val job = launch(Dispatchers.IO) { bot.run() }
        withTimeout(5000) { while (calls.none { it.first == "editMessageText" }) delay(20) }
        job.cancelAndJoin()
        assertTrue(texts().any { it.contains("Your Telegram user ID is 111") })
        assertEquals("Kill switch cancelled.", texts("editMessageText").last())
        // Offset advanced past the last update.
        assertEquals(7L, calls.last { it.first == "getUpdates" }.second["offset"]!!.jsonPrimitive.long)

        getUpdatesCode = 401
        val bot2 = TelegramBot(api(), FakeHost())
        withTimeout(5000) { bot2.run() }
        assertTrue(bot2.lastError!!.contains("401"))
    }
}
