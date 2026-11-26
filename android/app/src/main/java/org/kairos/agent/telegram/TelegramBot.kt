// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/telegram_bot.py: allowlisted command bot.
package org.kairos.agent.telegram

import kotlinx.coroutines.*

/** What the bot needs from the app; implemented by KairosApp, faked in tests. */
interface BotHost {
    fun allowedUserIds(): Set<Long>
    fun can(capability: String): Boolean
    fun activeCharacterName(): String
    fun characters(): List<Triple<String, String, String>> // id, name, description
    fun activeCharacterId(): String
    fun setCharacter(id: String): String? // returns name, or null when unknown
    suspend fun chat(prompt: String, onDelta: (String) -> Unit): String
    suspend fun search(query: String): List<Triple<String, String, String>> // title, url, description
    suspend fun learn(url: String): Pair<String, String> // title, summary
    suspend fun readMail(limit: Int): List<org.kairos.agent.email.MailItem>
    suspend fun sendMail(to: String, subject: String, body: String)
    fun remember(content: String): Boolean
    fun memories(): List<String>
    fun providers(): List<Pair<String, String>> // id, model
    fun activeProvider(): String
    fun setProvider(id: String): Boolean
    fun plans(): List<org.kairos.agent.agent.Plan>
    fun plan(id: String): org.kairos.agent.agent.Plan?
    fun newPlan(goal: String): String
    fun mode(): String
    fun setMode(mode: String): String
    suspend fun runAgent(goal: String, mode: String): String
    fun kill()
    fun skills(): List<Pair<String, String>> // name, description
    suspend fun runSkill(name: String, args: Map<String, String>): String
    suspend fun generateSkill(name: String, description: String): String
    fun createSkill(name: String, code: String): String
    suspend fun git(sub: String, rest: String): String
}

/** Commands handled on desktop that need a later Android feature (skills, media, git, …). */
private val LATER = setOf("download", "expired", "reflect", "lessons", "ports",
    "open", "send", "read", "close", "predict", "graph", "graphstats", "graphdel", "graphrepair", "pending",
    "usage", "tasks", "task", "deltask", "image", "webhooks", "write", "draw", "artifacts", "design", "browser")

class TelegramBot(
    private val api: TelegramApi,
    private val host: BotHost,
    private val editIntervalMs: Long = 1500,
) {
    @Volatile var lastError: String? = null; private set
    @Volatile var running = false; private set
    private var offset = 0L
    private val pendingSkill = java.util.concurrent.ConcurrentHashMap<Long, Pair<String, String>>()

    fun authorized(userId: Long?): Boolean = userId != null && userId in host.allowedUserIds()

    private fun denied(cap: String): String? =
        if (host.can(cap)) null else "'${host.activeCharacterName()}' is not permitted to use this capability (${cap.replace('_', ' ')})."

    /** Long-poll until cancelled. Network errors back off and retry; a rejected token stops the bot. */
    suspend fun run() = coroutineScope {
        running = true
        try {
            while (isActive) {
                val updates = try { api.getUpdates(offset) } catch (e: TelegramException) {
                    lastError = e.message; if (e.code == 401 || e.code == 404) return@coroutineScope
                    delay(5000); continue
                } catch (e: CancellationException) { throw e } catch (e: Exception) {
                    lastError = "Network: ${e.message}"; delay(5000); continue
                }
                lastError = null
                for (u in updates) {
                    offset = u.updateId + 1
                    // Each update runs on its own so a long /execute doesn't block /kill.
                    launch { runCatching { handle(u) }.onFailure { lastError = it.message } }
                }
            }
        } finally { running = false }
    }

    suspend fun handle(u: TgUpdate) {
        val chat = u.chatId ?: return
        if (u.callbackId != null) return handleCallback(u, chat)
        val text = u.text?.trim() ?: return
        if (!text.startsWith("/")) return
        val head = text.substringBefore(' ')
        val cmd = head.removePrefix("/").substringBefore('@').lowercase()
        val arg = text.substringAfter(' ', "").trim()
        suspend fun reply(s: String) { api.sendMessage(chat, s.take(3900)) }

        if (cmd == "whoami") return reply("Your Telegram user ID is ${u.userId ?: "?"}. Add it in KAIROS → Connect → Telegram → Allowed user IDs.")
        if (!authorized(u.userId)) return reply("Unauthorized. Ask the owner to add your Telegram user ID (${u.userId ?: "?"}) to the allowlist (send /whoami to see it).")

        when (cmd) {
            "start", "help" -> reply(HELP)
            "chat" -> if (arg.isEmpty()) reply("Usage: /chat <message>") else streamChat(chat, arg)
            "search" -> denied("web_search")?.let { reply(it) } ?: if (arg.isEmpty()) reply("Usage: /search <query>") else try {
                val r = host.search(arg)
                if (r.isEmpty()) reply("No results found.") else reply((listOf("Results for '$arg':") + r.take(10).mapIndexed { i, (t, url, d) ->
                    "${i + 1}. $t\n$url" + if (d.isNotBlank()) "\n   ${d.trim()}" else "" }).joinToString("\n"))
            } catch (e: Exception) { reply("Search error: ${e.message}") }
            "learn" -> denied("learn_web")?.let { reply(it) } ?: if (arg.isEmpty()) reply("Usage: /learn <url>") else {
                val url = arg.substringBefore(' ')
                reply("Scraping $url ...")
                try { val (t, s) = host.learn(url); reply("Learned from: $t\n\n${s.take(3500)}") } catch (e: Exception) { reply("Learn error: ${e.message}") }
            }
            "mail" -> denied("email_read")?.let { reply(it) } ?: try {
                val m = host.readMail(5)
                if (m.isEmpty()) reply("No email or email not configured.")
                else reply((listOf("Latest emails:") + m.map { "From: ${it.from}\nSubject: ${it.subject}\n${it.body.take(200)}" }).joinToString("\n\n").take(3500))
            } catch (e: Exception) { reply("Email error: ${e.message}") }
            "sendmail" -> denied("email_send")?.let { reply(it) } ?: run {
                val to = arg.substringBefore(' ').trim(); val rest = arg.substringAfter(' ', "")
                if (to.isEmpty() || rest.isEmpty()) return reply("Usage: /sendmail <to> <subject> | <body>")
                val subject = rest.substringBefore('|').trim(); val body = rest.substringAfter('|', "").trim()
                try { host.sendMail(to, subject, body); reply("Email sent.") } catch (e: Exception) { reply("Send error: ${e.message}") }
            }
            "remember" -> denied("memory")?.let { reply(it) } ?: if (arg.isEmpty()) reply("Usage: /remember <note or fact to save>") else {
                host.remember(arg); reply("Saved to retention.")
            }
            "memory" -> denied("memory")?.let { reply(it) } ?: host.memories().let { m ->
                reply(if (m.isEmpty()) "No retained data." else (listOf("Retained data:") + m.take(10).map { "- ${it.take(200)}" }).joinToString("\n"))
            }
            "character" -> reply((listOf("Active character: ${host.activeCharacterName()}", "", "Available characters:") +
                host.characters().map { (id, n, _) -> "${if (id == host.activeCharacterId()) "*" else "-"} $id  —  $n" } +
                listOf("", "Switch with: /setcharacter <id>")).joinToString("\n"))
            "setcharacter" -> if (arg.isEmpty()) reply("Usage: /setcharacter <id>") else
                host.setCharacter(arg.lowercase())?.let { reply("Now operating as: $it") } ?: reply("Could not switch character: unknown id '$arg'")
            "providers" -> reply((listOf("Active: ${host.activeProvider()}") + host.providers().map { (id, m) -> "- $id (model=$m)" }).joinToString("\n"))
            "setllm" -> if (arg.isEmpty()) reply("Usage: /setllm <provider_id>") else
                reply(if (host.setProvider(arg)) "Active LLM set to $arg" else "Provider '$arg' not found.")
            "plans" -> host.plans().let { p -> reply(if (p.isEmpty()) "No plans." else (listOf("Plans:") + p.take(20).map { "- ${it.id}  ${it.goal.take(60)}  [${it.status}]" }).joinToString("\n")) }
            "newplan" -> if (arg.isEmpty()) reply("Usage: /newplan <goal>") else reply("Plan created: ${host.newPlan(arg)}")
            "plan" -> if (arg.isEmpty()) reply("Usage: /plan <plan_id>") else host.plan(arg)?.let { p ->
                reply((listOf("${p.goal} [${p.status}]") + p.steps.map { "${it.idx}. [${it.status}] ${it.title}" }).joinToString("\n"))
            } ?: reply("Plan not found.")
            "mode" -> if (arg.isEmpty()) reply("Current mode: ${host.mode()}. Usage: /mode chat|plan|execute") else reply("Mode set to '${host.setMode(arg)}'.")
            "execute" -> if (arg.isEmpty()) reply("Usage: /execute <goal>") else {
                reply("Planning and executing...")
                reply(runCatching { host.runAgent(arg, "execute") }.getOrElse { "Error: ${it.message}" }.ifEmpty { "(no output)" })
            }
            "planagent" -> if (arg.isEmpty()) reply("Usage: /planagent <goal>") else
                reply(runCatching { host.runAgent(arg, "plan") }.getOrElse { "Error: ${it.message}" }.ifEmpty { "(no output)" })
            "skills" -> host.skills().let { k ->
                reply(if (k.isEmpty()) "No skills installed." else (listOf("Skills:") + k.map { (n, d) -> "- $n: $d" }).joinToString("\n"))
            }
            "runs" -> denied("skills_run")?.let { reply(it) } ?: if (arg.isEmpty()) reply("Usage: /runs <skill_name> [key=value ...]") else {
                val parts = arg.split(Regex("\\s+"))
                val args = parts.drop(1).filter { '=' in it }.associate { it.substringBefore('=') to it.substringAfter('=') }
                reply(try { "Result:\n" + host.runSkill(parts[0], args) } catch (e: Exception) { "Skill error: ${e.message}" })
            }
            "newskill" -> denied("skills_manage")?.let { reply(it) } ?: run {
                val name = arg.substringBefore(' ').trim().lowercase(); val desc = arg.substringAfter(' ', "").trim()
                if (name.isEmpty() || desc.isEmpty()) return reply("Usage: /newskill <name> <description>")
                if (!org.kairos.agent.skills.safeId(name)) return reply("Invalid name: use lowercase letters, digits and _ only.")
                reply("Generating skill '$name' ...")
                val code = host.generateSkill(name, desc)
                pendingSkill[chat] = name to code
                api.sendMessage(chat, "Proposed skill '$name':\n\n${code.take(3500)}",
                    listOf("Approve" to "approve_skill", "Reject" to "reject_skill")); Unit
            }
            "git" -> denied("git_ops")?.let { reply(it) } ?: run {
                val sub = arg.substringBefore(' ').lowercase(); val rest = arg.substringAfter(' ', "").trim()
                if (sub.isEmpty()) return reply("Usage: /git status|diff|log|branches|commit <msg>|branch <name>|checkout <name>|pull|push")
                if (sub == "commit" && rest.isEmpty()) return reply("Usage: /git commit <message>")
                reply(try { host.git(sub, rest) } catch (e: Exception) { "Git error: ${e.message}" })
            }
            "kill" -> { api.sendMessage(chat, "KILL SWITCH: shut down Kairos immediately?", listOf("YES - SHUT DOWN" to "confirm_kill", "Cancel" to "cancel_kill")); Unit }
            in LATER -> reply("/$cmd is not available in the Android app yet.")
            else -> reply("Unknown command. Send /help for the list.")
        }
    }

    /** Desktop _stream_chat: post "…", edit it at most every [editIntervalMs] while streaming, then finalize. */
    private suspend fun streamChat(chat: Long, prompt: String) = coroutineScope {
        val msgId = api.sendMessage(chat, "…")
        val buf = StringBuffer()
        val editor = launch {
            var shown = ""
            while (isActive) {
                delay(editIntervalMs)
                val t = buf.toString()
                if (t.isNotBlank() && t != shown) { shown = t; runCatching { api.editMessage(chat, msgId, t.take(3900)) } }
            }
        }
        val final = try { host.chat(prompt) { buf.append(it) } } catch (e: CancellationException) { throw e } catch (e: Exception) { "LLM error: ${e.message}" }
        editor.cancelAndJoin()
        api.editMessage(chat, msgId, final.ifBlank { "(no reply)" }.take(3900))
    }

    private suspend fun handleCallback(u: TgUpdate, chat: Long) {
        val id = u.callbackId!!
        if (!authorized(u.userId)) { api.answerCallback(id, "Unauthorized.", alert = true); return }
        api.answerCallback(id)
        val mid = u.messageId ?: return
        when (u.callbackData) {
            "confirm_kill" -> { api.editMessage(chat, mid, "Shutting down Kairos now."); host.kill() }
            "cancel_kill" -> api.editMessage(chat, mid, "Kill switch cancelled.")
            "approve_skill" -> {
                val d = denied("skills_manage")
                val p = pendingSkill.remove(chat)
                api.editMessage(chat, mid, when {
                    d != null -> d
                    p == null -> "No pending skill."
                    else -> runCatching { host.createSkill(p.first, p.second); "Skill '${p.first}' created." }.getOrElse { "Skill creation failed: ${it.message}" }
                })
            }
            "reject_skill" -> { pendingSkill.remove(chat); api.editMessage(chat, mid, "Skill rejected.") }
            else -> Unit
        }
    }

    companion object {
        val HELP = listOf(
            "KAIROS (Android) commands:",
            "/chat <text> - talk to the LLM",
            "/search <query> - web search",
            "/learn <url> - scrape page and store knowledge",
            "/mail - read email",
            "/sendmail <to> <subject> | <body> - send email",
            "/remember <text> - save to memory",
            "/memory - list retained data",
            "/providers - list LLM providers",
            "/setllm <id> - switch LLM",
            "/character - show/switch agent character",
            "/setcharacter <id> - activate a character",
            "/mode chat|plan|execute - set the agent mode",
            "/plans, /plan <id>, /newplan <goal> - durable plans",
            "/planagent <goal> - produce a durable plan",
            "/execute <goal> - plan and autonomously run the steps",
            "/skills - list skills",
            "/runs <name> [key=value ...] - run a skill",
            "/newskill <name> <description> - generate a skill (asks to approve)",
            "/git status|diff|log|branches|commit <msg>|branch <name>|checkout <name>|pull|push - git workflows",
            "/kill - kill switch (asks to confirm)",
            "/whoami - show your Telegram user ID",
        ).joinToString("\n")
    }
}
