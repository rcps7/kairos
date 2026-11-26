// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_skills_sandbox.py (name confinement + sandbox RPC), plus sandbox hardening
// and agent/character gating for the JavaScript skill runtime.
package org.kairos.agent

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.skills.*
import java.io.File
import java.nio.file.Files

class FakeSkillHost : SkillHost {
    val memories = mutableListOf<String>()
    override suspend fun askLlm(prompt: String) = "PONG"
    override suspend fun searchWeb(query: String, maxResults: Int): JsonElement =
        JsonArray(listOf(buildJsonObject { put("title", "T:$query"); put("url", "https://x.org"); put("description", "d") }))
    override suspend fun scrapePage(url: String): JsonElement = buildJsonObject { put("title", "Page"); put("text", "body of $url") }
    override suspend fun learnFromPage(url: String): JsonElement = throw SecurityException("not permitted: learn_web")
    override suspend fun addMemory(content: String) = memories.add(content)
    override suspend fun recall(query: String, limit: Int): JsonElement = JsonArray(memories.map { JsonPrimitive(it) })
}

class SkillsTest {
    private val hello = """
        // name: hello
        // description: test
        function run(kairos, args) { return "echo:" + kairos.ask_llm("hi"); }
    """.trimIndent()

    private fun mgr(timeoutMs: Long = 30_000): Pair<SkillManager, FakeSkillHost> {
        val h = FakeSkillHost()
        return SkillManager(Files.createTempDirectory("skills").toFile(), SkillSandbox(h, timeoutMs)) to h
    }

    @Test fun nameTraversalBlocked() {
        val (m, _) = mgr()
        assertEquals("", m.readSource("../evil"))
        for (bad in listOf("../evil", "a/b", "Evil", "", "x".repeat(41), "a.b")) {
            assertThrows(IllegalArgumentException::class.java) { m.saveSource(bad, "x=1") }
        }
        assertFalse(File(m.dir.parentFile, "evil.js").exists())
    }

    @Test fun sandboxRpc() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("hello", hello)
        assertEquals("echo:PONG", m.runSkill("hello"))
        assertEquals(listOf(SkillInfo("hello", "test")), m.listSkills())
        assertTrue(m.deleteSkill("hello")); assertTrue(m.listSkills().isEmpty())
    }

    @Test fun structuredRpcAndArgs() = runBlocking {
        val (m, h) = mgr()
        m.saveSource("combo", """
            function run(kairos, args) {
              var r = kairos.search_web(args.q, 3);
              kairos.add_memory("seen " + r[0].title);
              var p = kairos.scrape_page("https://a.b");
              return { first: r[0].title, page: p.text, mem: kairos.recall("x").length, n: Number(args.n) + 1 };
            }
        """.trimIndent())
        val out = Json.parseToJsonElement(m.runSkill("combo", mapOf("q" to "kotlin", "n" to "41"))).jsonObject
        assertEquals("T:kotlin", out["first"]!!.jsonPrimitive.content)
        assertEquals("body of https://a.b", out["page"]!!.jsonPrimitive.content)
        assertEquals(1, out["mem"]!!.jsonPrimitive.int)
        assertEquals(42, out["n"]!!.jsonPrimitive.int)
        assertEquals(listOf("seen T:kotlin"), h.memories)
    }

    @Test fun hostErrorsSurfaceAsJsExceptions() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("guard", """
            function run(kairos) {
              var msgs = [];
              try { kairos.learn_from_page("https://x"); } catch (e) { msgs.push(e.message); }
              try { kairos.call("send_email", {to: "a@b"}); } catch (e) { msgs.push(e.message); }
              return msgs.join("|");
            }
        """.trimIndent())
        assertEquals("not permitted: learn_web|method 'send_email' is not allowed", m.runSkill("guard"))
    }

    @Test fun noJavaOrHostEscape() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("escape", """
            function run(kairos) {
              var out = [typeof Packages, typeof java, typeof __host, typeof JavaImporter, typeof importPackage];
              try { kairos.ask_llm.constructor("return this")().__host.call("x", "{}"); out.push("leak"); } catch (e) { out.push("blocked"); }
              try { kairos.foo = 1; } catch (e) {}
              out.push(typeof kairos.foo);
              return out.join(",");
            }
        """.trimIndent())
        assertEquals("undefined,undefined,undefined,undefined,undefined,blocked,undefined", m.runSkill("escape"))
    }

    @Test fun infiniteLoopTimesOut() = runBlocking {
        val (m, _) = mgr(timeoutMs = 500)
        m.saveSource("spin", "function run() { while (true) {} }")
        val t0 = System.currentTimeMillis()
        val e = runCatching { m.runSkill("spin") }.exceptionOrNull()
        assertTrue(e is SkillError && e.message == "skill timed out")
        assertTrue(System.currentTimeMillis() - t0 < 5000)
    }

    @Test fun deepRecursionAndSyntaxErrorsAreContained() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("rec", "function f(n){return f(n+1)} function run(){ return f(0) }")
        assertTrue(runCatching { m.runSkill("rec") }.exceptionOrNull() is SkillError)
        m.saveSource("bad", "function run( { ")
        assertTrue(runCatching { m.runSkill("bad") }.exceptionOrNull()!!.message!!.startsWith("skill error"))
        m.saveSource("norun", "var x = 1;")
        assertEquals("no run(kairos, args) function found", runCatching { m.runSkill("norun") }.exceptionOrNull()!!.message)
        assertEquals("Skill 'ghost' not found.", runCatching { m.runSkill("ghost") }.exceptionOrNull()!!.message)
    }

    @Test fun templateRunsAndGeneratedCodeIsCleaned() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("stub", SkillManager.template("stub", "does a thing"))
        assertEquals("Skill stub executed.", m.runSkill("stub"))
        assertEquals("does a thing", m.listSkills().single().description)
        val fenced = "```javascript\nfunction run(k){return 'x'}\n```"
        assertEquals("function run(k){return 'x'}", SkillManager.stripCodeFences(fenced))
        assertTrue(SkillManager.looksValid(SkillManager.stripCodeFences(fenced)))
        assertFalse(SkillManager.looksValid("print('python')"))
    }

    @Test fun skillToolsRespectCapabilitiesAndAllowList() = runBlocking {
        val (m, _) = mgr()
        m.saveSource("hello", hello)
        m.saveSource("other", "function run(k, a){ return 'other:' + a.x }")
        val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
        val reg = CharacterRegistry(pack, listOf(
            pack.presets[0].copy(id = "limited", skills = listOf("hello")),
            pack.presets[0].copy(id = "norun", capabilities = listOf("memory"))))
        val tools = SkillTools(reg, m)
        assertEquals("other:7", tools.run(ToolCall("run_skill", mapOf("name" to "other", "args" to "{\"x\": 7}"))))
        reg.activeId = "limited"
        assertEquals("- hello: test", tools.run(ToolCall("list_skills")))
        assertTrue(tools.run(ToolCall("run_skill", mapOf("name" to "other"))).contains("not allowed"))
        assertEquals("echo:PONG", tools.run(ToolCall("run_skill", mapOf("name" to "hello"))))
        reg.activeId = "norun"
        assertEquals("(tool not permitted: skills_run)", tools.run(ToolCall("run_skill", mapOf("name" to "hello"))))
        // The advanced <tool> protocol reaches the skill tools.
        reg.activeId = "general"
        val (_, calls) = Tools.parse("<tool name=\"run_skill\">{\"name\": \"other\", \"args\": {\"x\": \"y\"}}</tool>")
        assertEquals("other:y", tools.run(calls[0]))
    }
}
