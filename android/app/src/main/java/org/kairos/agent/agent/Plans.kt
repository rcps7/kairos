// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/planner.py, structured.extract_json and
// KairosEngine.run_agent/_decompose/_execute_step (Plan and Execute modes).
package org.kairos.agent.agent

import kotlinx.serialization.json.*
import org.kairos.agent.llm.ChatMessage

data class PlanStep(val id: String, val idx: Int, val title: String, val status: String, val result: String)
data class Plan(val id: String, val goal: String, val status: String, val createdAt: Long, val steps: List<PlanStep>)

/** Durable plan storage; SQLite on device (MemoryStore), in-memory in unit tests. */
interface PlanStore {
    fun create(goal: String, steps: List<String> = emptyList()): String
    fun addStep(planId: String, title: String): String
    fun list(limit: Int = 50): List<Plan>
    fun get(planId: String): Plan?
    fun updateStep(stepId: String, status: String, result: String = "")
    fun setStatus(planId: String, status: String)
    fun delete(planId: String)
}

class InMemoryPlanStore : PlanStore {
    private val plans = LinkedHashMap<String, Plan>()
    private fun uid() = java.util.UUID.randomUUID().toString().replace("-", "")
    @Synchronized override fun create(goal: String, steps: List<String>): String {
        val id = uid(); plans[id] = Plan(id, goal, "open", System.currentTimeMillis(), emptyList())
        steps.forEach { addStep(id, it) }; return id
    }
    @Synchronized override fun addStep(planId: String, title: String): String {
        val p = plans[planId] ?: throw IllegalArgumentException("Plan not found")
        val s = PlanStep(uid(), p.steps.size, title, "todo", ""); plans[planId] = p.copy(steps = p.steps + s); return s.id
    }
    @Synchronized override fun list(limit: Int) = plans.values.reversed().take(limit)
    @Synchronized override fun get(planId: String) = plans[planId]
    @Synchronized override fun updateStep(stepId: String, status: String, result: String) {
        for ((k, p) in plans) if (p.steps.any { it.id == stepId })
            plans[k] = p.copy(steps = p.steps.map { if (it.id == stepId) it.copy(status = status, result = result.take(4000)) else it })
    }
    @Synchronized override fun setStatus(planId: String, status: String) { plans[planId]?.let { plans[planId] = it.copy(status = status) } }
    @Synchronized override fun delete(planId: String) { plans.remove(planId) }
}

object Structured {
    private val BLOCK = Regex("(\\{.*\\}|\\[.*\\])", RegexOption.DOT_MATCHES_ALL)
    private val json = Json { isLenient = true }

    /** Desktop structured.extract_json: strip code fences, take the outermost JSON block, parse. */
    fun extractJson(text: String?): JsonElement? {
        if (text.isNullOrBlank()) return null
        var t = text.trim()
        if (t.startsWith("```")) t = t.replace(Regex("^```[a-zA-Z]*\\n?"), "").replace(Regex("\\n?```$"), "").trim()
        BLOCK.find(t)?.let { t = it.value }
        return try { json.parseToJsonElement(t) } catch (_: Exception) { null }
    }
}

const val PLANNER_SYSTEM = "You are a planning engine. Decompose the user's goal into a short, ordered list of " +
    "concrete, independently executable steps. Reply with ONLY a JSON array of step strings (3-10 steps) and " +
    "nothing else — no prose, no code fences. Each step must be a single actionable instruction."

fun planPrompt(goal: String, context: String = ""): String {
    val ctx = if (context.isNotEmpty()) "\n\nCONTEXT:\n${context.take(4000)}" else ""
    return "GOAL:\n$goal$ctx\n\nReturn the JSON array of steps now, and nothing else."
}

fun formatPlan(steps: List<String>): String =
    (listOf("Plan:") + steps.mapIndexed { i, s -> "  ${i + 1}. $s" }).joinToString("\n")

fun formatPlanStatus(p: Plan): String =
    (listOf("${p.goal} [${p.status}]") + p.steps.map { "  ${it.idx}. [${it.status}] ${it.title}" }).joinToString("\n")

data class AgentResult(val mode: String, val text: String, val planId: String? = null, val steps: List<String> = emptyList())

/** Plan / Execute modes on top of the chat engine (desktop run_agent). */
class Agent(
    private val engine: Engine,
    private val backend: ChatBackend,
    private val plans: PlanStore,
    private val memory: AgentMemory,
) {
    suspend fun decompose(goal: String, context: String = ""): List<String> {
        val raw = try {
            backend.complete(listOf(ChatMessage("system", PLANNER_SYSTEM), ChatMessage("user", planPrompt(goal, context))), null)
        } catch (e: Exception) { return listOf("Complete the goal: $goal") }
        val data = Structured.extractJson(raw)
        var steps: List<String> = when (data) {
            is JsonArray -> data.map { el -> ((el as? JsonPrimitive)?.contentOrNull ?: el.toString()).trim() }
            is JsonObject -> (data["steps"] as? JsonArray)?.map { el -> ((el as? JsonPrimitive)?.contentOrNull ?: el.toString()).trim() } ?: emptyList()
            else -> emptyList()
        }.filter { it.isNotEmpty() }
        if (steps.isEmpty() && raw.isNotBlank())
            steps = raw.lines().map { it.trim(' ', '-', '*', '\t', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.') }.filter { it.isNotEmpty() }
        return steps.take(10).ifEmpty { listOf("Complete the goal: $goal") }
    }

    suspend fun run(prompt: String, mode: String, progress: ((String) -> Unit)? = null, onDelta: ((String) -> Unit)? = null): AgentResult {
        val m = mode.lowercase().takeIf { it in setOf("chat", "plan", "execute") } ?: "chat"
        if (m == "chat") return AgentResult("chat", engine.chat(prompt, onDelta))
        val steps = decompose(prompt)
        val planId = plans.create(prompt, steps)
        progress?.invoke("Plan created: ${steps.size} step(s).")
        if (m == "plan") return AgentResult("plan", formatPlan(steps) + "\n\n(plan id: $planId)", planId, steps)

        val plan = plans.get(planId)!!
        val results = mutableListOf<String>()
        plan.steps.forEachIndexed { i, st ->
            progress?.invoke("Executing step ${i + 1}/${plan.steps.size}: ${st.title}")
            plans.updateStep(st.id, "doing")
            val out = try {
                executeStep(prompt, st.title, results).also { plans.updateStep(st.id, "done", it) }
            } catch (e: Exception) {
                "(step failed: ${e.message})".also { plans.updateStep(st.id, "error", it) }
            }
            results += "${i + 1}. ${st.title}\n$out"
        }
        plans.setStatus(planId, "done")
        val final = results.joinToString("\n\n")
        runCatching { memory.remember("[Task] $prompt\n${final.take(3000)}") }
        return AgentResult("execute", "Executed plan ($planId):\n\n$final", planId, steps)
    }

    private suspend fun executeStep(goal: String, step: String, prior: List<String>): String {
        val conv = "GOAL:\n$goal\n\nPRIOR RESULTS:\n" + prior.joinToString("\n").take(4000) +
            "\n\nCURRENT STEP:\n$step\n\nComplete ONLY this step. Use tools when needed; report the concrete result."
        return engine.runTurn(conv)
    }
}

/** Plan tools for the advanced <tool name="..."> protocol (desktop toolkit plan_*). */
class PlanTools(private val plans: PlanStore, private val next: ToolRunner? = null) : ToolRunner {
    override suspend fun run(call: ToolCall): String {
        val a = call.args
        return when (call.name) {
            "plan_create" -> {
                val steps = a["steps"]?.let { s -> (Structured.extractJson(s) as? JsonArray)?.map { (it as? JsonPrimitive)?.contentOrNull ?: it.toString() } } ?: emptyList()
                "Plan created: ${plans.create(a["goal"].orEmpty(), steps)}"
            }
            "plan_add_step" -> try { "Step added: ${plans.addStep(a["plan_id"].orEmpty(), a["title"].orEmpty())}" } catch (e: IllegalArgumentException) { "Plan not found." }
            "plan_update_step" -> { plans.updateStep(a["step_id"].orEmpty(), a["status"].orEmpty(), a["result"].orEmpty()); "Step updated." }
            "plan_status" -> plans.get(a["plan_id"].orEmpty())?.let(::formatPlanStatus) ?: "Plan not found."
            else -> next?.run(call) ?: "(unknown tool: ${call.name})"
        }
    }
}
