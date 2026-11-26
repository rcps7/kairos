// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Browser Agent tools (gated by browser_control) and serial
// peripheral tools (gated by peripherals), with the desktop tool names.
package org.kairos.agent.agent

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.kairos.agent.browser.BrowserAgent
import org.kairos.agent.serial.SerialPorts
import org.kairos.agent.serial.SerialText

class BrowserTools(
    private val characters: CharacterRegistry,
    private val browser: () -> BrowserAgent,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String {
        if (!call.name.startsWith("browser_")) return next?.run(call) ?: "(unknown tool: ${call.name})"
        // browser_captcha only detects (desktop: ungated); everything else needs browser_control.
        if (call.name != "browser_captcha" && !characters.can("browser_control")) return "(tool not permitted: browser_control)"
        val a = call.args
        val b = browser()
        return try {
            when (call.name) {
                "browser_open", "browser_goto", "browser_fetch" -> b.goto(a["url"].orEmpty())
                "browser_read" -> b.read(a["selector"] ?: a["target"])
                "browser_inputs" -> b.forms()
                "browser_fill" -> b.fill(a["target"] ?: a["selector"] ?: a["label"].orEmpty(), a["value"] ?: a["text"].orEmpty())
                "browser_form" -> b.form(formFields(a))
                "browser_click" -> b.click(a["target"] ?: a["selector"] ?: a["text"].orEmpty())
                "browser_mouse" -> {
                    val x = a["x"]?.toIntOrNull(); val y = a["y"]?.toIntOrNull()
                    if (x != null && y != null) b.mouse(x, y) else b.click(a["selector"] ?: a["target"].orEmpty())
                }
                "browser_key" -> b.key(a["target"], a["key"] ?: "Enter")
                "browser_js" -> b.js(a["code"] ?: a["script"].orEmpty())
                "browser_action" -> b.actions(a["steps"] ?: a["actions"] ?: "[]")
                "browser_back" -> b.back()
                "browser_forward" -> b.forward()
                "browser_reload" -> b.reload()
                "browser_screenshot" -> { a["url"]?.takeIf { it.isNotBlank() }?.let { b.goto(it) }; b.screenshot() }
                "browser_captcha" -> b.captcha()
                else -> "(unknown tool: ${call.name})"
            }
        } catch (e: Exception) { "(browser error: ${e.message})" }
    }

    private fun formFields(a: Map<String, String>): Map<String, String> =
        a["fields"]?.let { f -> Json.parseToJsonElement(f).jsonObject.mapValues { it.value.jsonPrimitive.content } }
            ?: a.filterKeys { it != "fields" }
}

class SerialTools(
    private val characters: CharacterRegistry,
    private val ports: () -> SerialPorts,
    private val next: ToolRunner? = null,
) : ToolRunner {
    override suspend fun run(call: ToolCall): String {
        if (!call.name.startsWith("serial_")) return next?.run(call) ?: "(unknown tool: ${call.name})"
        if (!characters.can("peripherals")) return "(tool not permitted: peripherals)"
        val a = call.args
        val dev = a["device"] ?: a["port"] ?: "0"
        val baud = a["baud"]?.toIntOrNull() ?: a["baudrate"]?.toIntOrNull() ?: 115200
        val p = ports()
        return withContext(Dispatchers.IO) {
            try {
                when (call.name) {
                    "serial_list" -> p.list().takeIf { it.isNotEmpty() }?.mapIndexed { i, d ->
                        "$i. ${d.id} — ${d.description} [${d.chip?.label}]" + if (d.permitted) "" else " (needs USB permission)"
                    }?.joinToString("\n") ?: "(no USB serial devices; connect a board with a USB OTG adapter)"
                    "serial_open" -> p.open(dev, baud)
                    "serial_close" -> { p.close(dev); "Closed $dev." }
                    "serial_write" -> { val n = p.write(dev, SerialText.unescape(a["data"] ?: a["text"].orEmpty())); "Wrote $n bytes." }
                    "serial_read" -> SerialText.show(p.read(dev, a["timeout_ms"]?.toLongOrNull() ?: 1500)).ifEmpty { "(no data)" }
                    "serial_send" -> {
                        if (!p.isOpen(dev)) { val r = p.open(dev, baud); if (!r.startsWith("Opened")) return@withContext r }
                        val data = a["data"] ?: a["text"].orEmpty()
                        p.write(dev, SerialText.unescape(if (a["newline"] == "false" || data.endsWith("\\n")) data else data + "\\n"))
                        SerialText.show(p.read(dev, a["timeout_ms"]?.toLongOrNull() ?: 1500)).ifEmpty { "(sent; no reply)" }
                    }
                    else -> "(unknown tool: ${call.name})"
                }
            } catch (e: Exception) { "(serial error: ${e.message})" }
        }
    }
}
