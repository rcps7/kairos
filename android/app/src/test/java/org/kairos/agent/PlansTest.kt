// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_wave1.py (planner store, structured JSON, plan_status) and tests/test_modes.py
// (planner prompt), plus Plan/Execute mode runs (desktop run_agent).
package org.kairos.agent

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.int
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.llm.ChatMessage
import java.io.File

class PlansTest {
    private val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())

    @Test fun plannerStore() {
        val st = InMemoryPlanStore()
        val pid = st.create("Build a robot", listOf("design", "assemble"))
        assertEquals(1, st.list().size)
        val plan = st.get(pid)!!
        assertEquals(listOf("design", "assemble"), plan.steps.map { it.title })
        st.updateStep(plan.steps[0].id, "done", "ok")
        assertEquals("done", st.get(pid)!!.steps[0].status)
        st.delete(pid); assertNull(st.get(pid))
    }

    @Test fun structuredExtractJson() {
        assertEquals(1, (Structured.extractJson("```json\n{\"a\": 1}\n```") as JsonObject)["a"]!!.jsonPrimitive.int)
        assertEquals(2, (Structured.extractJson("Sure! [\"x\", \"y\"] done") as JsonArray).size)
        assertNull(Structured.extractJson("not json"))
    }

    @Test fun plannerPrompt() {
        val p = planPrompt("build a thing", "some context")
        assertTrue(p.contains("build a thing") && p.contains("JSON"))
    }

    @Test fun planToolsStatus() = runTest {
        val st = InMemoryPlanStore()
        val t = PlanTools(st)
        val created = t.run(ToolCall("plan_create", mapOf("goal" to "g", "steps" to "[\"t\"]")))
        val pid = created.removePrefix("Plan created: ")
        assertTrue(t.run(ToolCall("plan_status", mapOf("plan_id" to pid))).startsWith("g"))
        assertTrue(t.run(ToolCall("plan_add_step", mapOf("plan_id" to pid, "title" to "u"))).startsWith("Step added"))
        assertEquals("Plan not found.", t.run(ToolCall("plan_status", mapOf("plan_id" to "nope"))))
        assertEquals("Plan not found.", t.run(ToolCall("plan_add_step", mapOf("plan_id" to "nope", "title" to "u"))))
    }

    @Test fun genericToolCallReachesPlanTools() = runTest {
        val st = InMemoryPlanStore()
        val (_, calls) = Tools.parse("<tool name=\"plan_create\">{\"goal\": \"ship\", \"steps\": [\"a\", \"b\"]}</tool>")
        PlanTools(st).run(calls[0])
        assertEquals(listOf("a", "b"), st.list().single().steps.map { it.title })
    }

    private fun agent(replies: MutableList<String>, st: PlanStore, mem: FakeMemory = FakeMemory(), seen: MutableList<List<ChatMessage>> = mutableListOf()): Agent {
        val backend = ChatBackend { msgs, _ -> seen += msgs; if (replies.isEmpty()) "fallback" else replies.removeAt(0) }
        val reg = CharacterRegistry(pack)
        return Agent(Engine(reg, mem, backend, tools = PlanTools(st)), backend, st, mem)
    }

    @Test fun decomposeParsesJsonOrLinesAndFallsBack() = runTest {
        val st = InMemoryPlanStore()
        assertEquals(listOf("a", "b"), agent(mutableListOf("```json\n[\"a\", \"b\"]\n```"), st).decompose("g"))
        assertEquals(listOf("x", "y"), agent(mutableListOf("{\"steps\": [\"x\", \"y\"]}"), st).decompose("g"))
        assertEquals(listOf("first", "second"), agent(mutableListOf("1. first\n2. second"), st).decompose("g"))
        assertEquals(listOf("Complete the goal: g"), agent(mutableListOf(""), st).decompose("g"))
    }

    @Test fun planModeCreatesDurablePlanWithoutExecuting() = runTest {
        val st = InMemoryPlanStore()
        val r = agent(mutableListOf("[\"design\", \"assemble\"]"), st).run("Build a robot", "plan")
        assertEquals("plan", r.mode)
        assertTrue(r.text.startsWith("Plan:\n  1. design\n  2. assemble"))
        assertEquals(listOf("todo", "todo"), st.get(r.planId!!)!!.steps.map { it.status })
    }

    @Test fun executeModeRunsEveryStepAndRecordsResults() = runTest {
        val st = InMemoryPlanStore(); val mem = FakeMemory(); val seen = mutableListOf<List<ChatMessage>>()
        val r = agent(mutableListOf("[\"design\", \"assemble\"]", "designed it", "assembled it"), st, mem, seen).run("Build a robot", "execute")
        assertEquals("execute", r.mode)
        val plan = st.get(r.planId!!)!!
        assertEquals("done", plan.status)
        assertEquals(listOf("done" to "designed it", "done" to "assembled it"), plan.steps.map { it.status to it.result })
        assertTrue(r.text.contains("1. design\ndesigned it")); assertTrue(r.text.contains("2. assemble\nassembled it"))
        // Second step sees the first step's result; the advanced tool protocol is offered.
        assertTrue(seen[2].last().content.contains("PRIOR RESULTS:\n1. design\ndesigned it"))
        assertTrue(seen[2].first().content.contains("ADVANCED TOOLS"))
        assertTrue(mem.mem.single().startsWith("[Task] Build a robot"))
    }

    @Test fun executeStepCanUseTools() = runTest {
        val st = InMemoryPlanStore()
        val r = agent(mutableListOf("[\"check plans\"]", "<tool name=\"plan_status\">{\"plan_id\": \"none\"}</tool>", "No such plan."), st)
            .run("audit", "execute")
        assertEquals("No such plan.", st.get(r.planId!!)!!.steps.single().result)
    }

    @Test fun unknownModeFallsBackToChat() = runTest {
        val r = agent(mutableListOf("hello"), InMemoryPlanStore()).run("hi", "bogus")
        assertEquals("chat", r.mode); assertEquals("hello", r.text)
    }
}
