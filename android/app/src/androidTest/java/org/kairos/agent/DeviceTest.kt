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

    /** Desktop planner.py on SQLite: create, list, update, delete. */
    @Test fun planStoreOnSqlite() {
        val m = MemoryStore(ctx, null)
        val pid = m.create("Build a robot", listOf("design", "assemble"))
        assertEquals(1, m.list().size)
        val p = m.get(pid)!!
        assertEquals(listOf(0, 1), p.steps.map { it.idx })
        m.updateStep(p.steps[0].id, "done", "ok")
        assertEquals("done" to "ok", m.get(pid)!!.steps[0].let { it.status to it.result })
        m.addStep(pid, "test"); assertEquals(3, m.get(pid)!!.steps.size)
        m.delete(pid); assertNull(m.get(pid))
    }

    @Test fun plansTabAndModeChipsShow() {
        compose.onNodeWithTag("mode_execute").assertIsDisplayed()
        compose.onNodeWithTag("tab_Plans").performClick()
        compose.onNodeWithTag("plans").assertIsDisplayed()
    }

    /** Email & Telegram settings open, save, and a malformed bot token is refused by the service. */
    @Test fun connectScreenSavesSettings() {
        compose.onNodeWithTag("more").performClick(); compose.onNodeWithTag("tab_Connect").performClick()
        compose.onNodeWithTag("connect").assertIsDisplayed()
        compose.onNodeWithTag("email_save").performClick()
        compose.onNodeWithTag("mail_status").assertTextContains("Saved.")
        compose.onNodeWithTag("connect").performScrollToNode(hasTestTag("tg_token"))
        compose.onNodeWithTag("tg_token").performTextInput("not-a-token")
        compose.onNodeWithTag("connect").performScrollToNode(hasTestTag("tg_switch"))
        compose.onNodeWithTag("tg_switch").performClick()
        compose.waitUntil(5000) {
            org.kairos.agent.telegram.TelegramService.status.contains("format looks wrong")
        }
        compose.onNodeWithTag("tg_switch").performClick() // turn back off
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        assertFalse(app.settings.telegramEnabled)
        app.secrets.put(SecureStore.TELEGRAM_TOKEN, null)
    }

    /** A JavaScript skill is saved and runs in the Rhino sandbox on the device. */
    @Test fun skillSavesAndRunsOnDevice() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        compose.onNodeWithTag("more").performClick(); compose.onNodeWithTag("tab_Skills").performClick()
        compose.onNodeWithTag("skill_name").performTextInput("device_echo")
        compose.onNodeWithTag("skill_code").performTextInput(
            "// description: device test\nfunction run(k, a) { var s = 0; for (var i = 1; i <= 100; i++) s += i; return 'sum=' + s + ' ' + a.who; }")
        compose.onNodeWithTag("skills").performScrollToNode(hasTestTag("skill_save"))
        compose.onNodeWithTag("skill_save").performClick()
        assertTrue(app.skills.listSkills().any { it.name == "device_echo" && it.description == "device test" })
        val out = kotlinx.coroutines.runBlocking { app.skills.runSkill("device_echo", mapOf("who" to "android")) }
        assertEquals("sum=5050 android", out)
        compose.onNodeWithTag("skills").performScrollToNode(hasTestTag("skill_run"))
        compose.onNodeWithTag("skill_run").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithTag("skill_output").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("skill_output").assertTextContains("sum=5050", substring = true)
        app.skills.deleteSkill("device_echo")
    }

    /** JGit works on the device: init, commit and log through the Git screen and GitTool. */
    @Test fun gitInitCommitLogOnDevice() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        val dir = java.io.File(app.git.root, "device_repo"); dir.deleteRecursively()
        compose.onNodeWithTag("more").performClick(); compose.onNodeWithTag("tab_Git").performClick()
        if (!app.settings.gitEnabled) compose.onNodeWithTag("git_enabled").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        compose.onNodeWithTag("git_repo").performTextClearance()
        compose.onNodeWithTag("git_repo").performTextInput("device_repo")
        compose.onNodeWithTag("git_init").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        fun gitOut(): String {
            val key = androidx.compose.ui.semantics.SemanticsProperties.Text
            val c = compose.onAllNodesWithTag("git_out").fetchSemanticsNodes().firstOrNull()?.config ?: return ""
            return if (key in c) c[key].joinToString { t -> t.text } else ""
        }
        compose.waitUntil(15000) { java.io.File(dir, ".git").isDirectory || gitOut().let { it.isNotEmpty() && !it.endsWith("…") } }
        assertTrue("git screen said: ${gitOut()}", java.io.File(dir, ".git").isDirectory)
        java.io.File(dir, "notes.txt").writeText("hello from android")
        compose.onNodeWithTag("git").performScrollToNode(hasTestTag("git_message"))
        compose.onNodeWithTag("git_message").performTextInput("first android commit")
        compose.onNodeWithTag("git").performScrollToNode(hasTestTag("git_commit"))
        compose.onNodeWithTag("git_commit").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        compose.waitUntil(15000) { runCatching { app.git.log(5, "device_repo") }.getOrDefault("").contains("first android commit") }
        assertTrue(app.git.status("device_repo").contains("clean working tree"))
        app.settings.gitEnabled = false
        dir.deleteRecursively()
    }

    /** yt-dlp (Python) runs on the device: a direct MP4 from a local HTTP server is downloaded and indexed. */
    @Test fun mediaDownloadOnDevice() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        // The `fdroid` flavour has no yt-dlp; this test only runs on the `full` build.
        org.junit.Assume.assumeTrue("media download needs the 'full' build", app.media.available())
        val payload = ByteArray(64 * 1024) { (it % 251).toByte() }
        val server = java.net.ServerSocket(0, 50, java.net.InetAddress.getByName("127.0.0.1"))
        val t = Thread {
            while (!server.isClosed) {
                val sock = runCatching { server.accept() }.getOrNull() ?: break
                sock.use { s ->
                    val r = s.getInputStream().bufferedReader()
                    val first = r.readLine() ?: return@use
                    while (true) { val l = r.readLine() ?: break; if (l.isEmpty()) break }
                    val head = first.startsWith("HEAD")
                    val o = s.getOutputStream()
                    o.write(("HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: ${payload.size}\r\n" +
                        "Accept-Ranges: none\r\nConnection: close\r\n\r\n").toByteArray())
                    if (!head) o.write(payload)
                    o.flush()
                }
            }
        }.apply { isDaemon = true; start() }
        try {
            val item = app.media.download("http://127.0.0.1:${server.localPort}/clip.mp4", "mp4")
            assertEquals("video", item.type)
            val f = java.io.File(item.path)
            assertTrue("file exists: ${item.path}", f.isFile)
            assertEquals(payload.size.toLong(), f.length())
            assertTrue(app.media.index.list().any { it.id == item.id })
            app.media.index.remove(item.id)
        } finally { server.close(); t.join(2000) }
    }

    /** The Speak toggle persists and the Talk button is present. */
    @Test fun voiceControlsPresent() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        val before = app.settings.speakReplies
        compose.onNodeWithTag("talk").assertIsDisplayed()
        compose.onNodeWithTag("speak").performClick()
        assertEquals(!before, app.settings.speakReplies)
        compose.onNodeWithTag("speak").performClick()
        assertEquals(before, app.settings.speakReplies)
        assertEquals("Hello world. code: (code omitted)", org.kairos.agent.voice.VoiceText.forSpeech("**Hello** world. code: ```x=1```"))
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

    /** Browser Agent on a real WebView: open a local page, fill a form by label, submit by button text, read the result. */
    @Test fun browserAgentFillsFormOnDevice() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        val form = "<html><head><title>Form</title></head><body><form action='/done' method='get'>" +
            "<label for='n'>Your name</label><input id='n' name='who'><button type='submit'>Send</button></form></body></html>"
        val server = java.net.ServerSocket(0, 50, java.net.InetAddress.getByName("127.0.0.1"))
        Thread {
            while (!server.isClosed) {
                val sock = runCatching { server.accept() }.getOrNull() ?: break
                sock.use { s ->
                    val r = s.getInputStream().bufferedReader()
                    val first = r.readLine() ?: return@use
                    while (true) { val l = r.readLine() ?: break; if (l.isEmpty()) break }
                    val path = first.split(" ").getOrElse(1) { "/" }
                    val body = if (path.startsWith("/done")) "<html><body><h1>Hello " +
                        java.net.URLDecoder.decode(path.substringAfter("who=", ""), "UTF-8") + "</h1></body></html>" else form
                    val bytes = body.toByteArray()
                    s.getOutputStream().apply {
                        write(("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n").toByteArray())
                        write(bytes); flush()
                    }
                }
            }
        }.apply { isDaemon = true; start() }
        try {
            val tools = org.kairos.agent.agent.BrowserTools(app.characters, { app.browserAgent })
            kotlinx.coroutines.runBlocking {
                val opened = tools.run(org.kairos.agent.agent.ToolCall("browser_goto", mapOf("url" to "http://127.0.0.1:${server.localPort}/")))
                assertTrue(opened, opened.contains("Your name"))
                val inputs = tools.run(org.kairos.agent.agent.ToolCall("browser_inputs"))
                assertTrue(inputs, inputs.contains("\"label\":\"Your name\""))
                val filled = tools.run(org.kairos.agent.agent.ToolCall("browser_fill", mapOf("target" to "Your name", "value" to "Kairos")))
                assertEquals("filled input#n[name=who]", filled)
                val clicked = tools.run(org.kairos.agent.agent.ToolCall("browser_click", mapOf("target" to "Send")))
                assertTrue(clicked, clicked.contains("/done?who=Kairos"))
                val read = tools.run(org.kairos.agent.agent.ToolCall("browser_read", mapOf("selector" to "h1")))
                assertEquals("Hello Kairos", read)
                val shot = tools.run(org.kairos.agent.agent.ToolCall("browser_screenshot"))
                assertTrue(shot, shot.startsWith("Screenshot saved:") && java.io.File(shot.substringAfter(": ")).length() > 0)
            }
            // The same WebView shows in the Browser screen with the agent's page.
            compose.onNodeWithTag("more").performClick(); compose.onNodeWithTag("tab_Browser").performClick()
            compose.onNodeWithTag("browser_view").assertExists()
            compose.onNodeWithTag("browser_url").assertTextContains("/done?who=Kairos", substring = true)
        } finally { server.close() }
    }

    /** USB serial: the emulator has no USB host devices, so the screen and tool report none (driver logic is unit-tested). */
    @Test fun serialScreenOnDevice() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as KairosApp
        compose.onNodeWithTag("more").performClick(); compose.onNodeWithTag("tab_Serial").performClick()
        compose.onNodeWithTag("serial").assertExists()
        val out = kotlinx.coroutines.runBlocking { org.kairos.agent.agent.SerialTools(app.characters, { app.serialPorts })
            .run(org.kairos.agent.agent.ToolCall("serial_list")) }
        if (app.serialPorts.list().isEmpty()) {
            compose.onNodeWithTag("serial_none").assertExists()
            assertTrue(out, out.contains("no USB serial devices"))
        }
    }
}
