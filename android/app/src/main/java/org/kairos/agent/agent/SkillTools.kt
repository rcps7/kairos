// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Skill tools for the agent (desktop list_skills / run_skill),
// gated by the skills_run capability and the active character's skill allow-list.
package org.kairos.agent.agent

import kotlinx.serialization.json.*
import org.kairos.agent.skills.SkillManager

class SkillTools(
    private val characters: CharacterRegistry,
    private val skills: SkillManager,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String = when (call.name) {
        "list_skills" -> skills.listSkills().filter { characters.allowsSkill(it.name) }
            .joinToString("\n") { "- ${it.name}: ${it.description}" }.ifEmpty { "(no skills)" }
        "run_skill" -> runSkill(call.args)
        else -> next?.run(call) ?: "(unknown tool: ${call.name})"
    }

    private suspend fun runSkill(a: Map<String, String>): String {
        val name = a["name"].orEmpty().trim()
        if (!characters.can("skills_run")) return "(tool not permitted: skills_run)"
        if (!characters.allowsSkill(name)) return "(skill '$name' is not allowed for the active character)"
        val args: Map<String, String> = a["args"]?.let { raw ->
            runCatching { Json.parseToJsonElement(raw).jsonObject.mapValues { (_, v) -> (v as? JsonPrimitive)?.contentOrNull ?: v.toString() } }.getOrNull()
        } ?: a.filterKeys { it != "name" }
        return try { skills.runSkill(name, args) } catch (e: Exception) { "(skill error: ${e.message})" }
    }
}
