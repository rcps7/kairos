// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Email tools for the agent (desktop read_email / send_email,
// gated by the email_read and email_send capabilities).
package org.kairos.agent.agent

import org.kairos.agent.email.EmailClient

class EmailTools(
    private val characters: CharacterRegistry,
    private val client: EmailClient,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String = when (call.name) {
        "read_email" -> if (!characters.can("email_read")) "(tool not permitted: email_read)" else try {
            EmailClient.format(client.readMail(call.args["limit"]?.toIntOrNull()?.coerceIn(1, 20) ?: 5), 500)
        } catch (e: Exception) { "(tool error: ${e.message})" }
        "send_email" -> if (!characters.can("email_send")) "(tool not permitted: email_send)" else try {
            val to = call.args["to"].orEmpty()
            if (to.isBlank()) "(no recipient provided)"
            else { client.sendMail(to, call.args["subject"].orEmpty(), call.args["body"].orEmpty()); "Email sent to $to." }
        } catch (e: Exception) { "(tool error: ${e.message})" }
        else -> next?.run(call) ?: "(unknown tool: ${call.name})"
    }
}
