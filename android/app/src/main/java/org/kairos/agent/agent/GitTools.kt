// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Git tools for the agent (desktop toolkit git_*), gated by git_ops.
package org.kairos.agent.agent

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.kairos.agent.git.GitTool

class GitTools(
    private val characters: CharacterRegistry,
    private val git: GitTool,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String {
        if (!call.name.startsWith("git_")) return next?.run(call) ?: "(unknown tool: ${call.name})"
        if (!characters.can("git_ops")) return "(tool not permitted: git_ops)"
        val a = call.args
        val repo = a["repo"]?.takeIf { it.isNotBlank() }
        return withContext(Dispatchers.IO) {
            try {
                when (call.name) {
                    "git_status" -> git.status(repo)
                    "git_diff" -> git.diff(a["staged"] == "true", a["ref"], repo)
                    "git_log" -> git.log(a["n"]?.toIntOrNull() ?: 20, repo)
                    "git_branches" -> git.branches(repo)
                    "git_commit" -> git.commit(a["message"].orEmpty(), a["add_all"] != "false", repo)
                    "git_branch" -> git.createBranch(a["name"].orEmpty(), a["checkout"] != "false", repo)
                    "git_checkout" -> git.checkout(a["name"].orEmpty(), repo)
                    "git_pull" -> git.pull(repo)
                    "git_push" -> git.push(a["remote"] ?: "origin", a["branch"], repo)
                    else -> "(unknown tool: ${call.name})"
                }
            } catch (e: Exception) { "(git error: ${e.message})" }
        }
    }
}
