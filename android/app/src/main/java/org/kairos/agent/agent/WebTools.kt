// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of KairosEngine._run_tool / search_web / scrape_page / learn_from_page.
package org.kairos.agent.agent

import org.kairos.agent.web.Page
import org.kairos.agent.web.SearchResult
import org.kairos.agent.web.WebSearcher
import org.kairos.agent.web.summarizePrompt

/** Executes one model-requested tool; returns text for the model. */
fun interface ToolRunner {
    suspend fun run(call: ToolCall): String
}

/** Knowledge library the web tools write into (MemoryStore on device, a fake in tests). */
interface Library {
    fun add(url: String, title: String, html: String, text: String, summary: String): String
}

class WebTools(
    private val characters: CharacterRegistry,
    private val search: suspend (String, Int) -> List<SearchResult>,
    private val fetch: suspend (String) -> Page,
    private val summarize: suspend (String) -> String,
    private val library: Library,
    private val fallback: ToolRunner? = null,
) : ToolRunner {

    data class Learned(val id: String, val url: String, val title: String, val summary: String)

    suspend fun learn(url: String): Learned {
        require(characters.can("learn_web")) { "learn_web" }
        val page = fetch(url)
        val summary = summarize(summarizePrompt(page.text))
        val id = library.add(url, page.title, page.html, page.text, summary)
        return Learned(id, url, page.title, summary)
    }

    override suspend fun run(call: ToolCall): String = try {
        when (call.name) {
            "web_search" -> {
                if (!characters.can("web_search")) throw SecurityException("web_search")
                if (call.query.isEmpty()) "(no search query provided)"
                else search(call.query, 8).let { r ->
                    if (r.isEmpty()) "(no results for: ${call.query})" else WebSearcher.format(r)
                }
            }
            "learn_web", "scrape" -> {
                if (!characters.can("learn_web")) throw SecurityException("learn_web")
                when {
                    call.url.isEmpty() -> "(no url provided)"
                    call.name == "learn_web" -> learn(call.url).let { "Page: ${it.title}\n${it.summary}" }
                    else -> fetch(call.url).let { "Page: ${it.title}\n${it.text.take(6000)}" }
                }
            }
            else -> fallback?.run(call) ?: "(unknown tool: ${call.name})"
        }
    } catch (e: SecurityException) {
        "(tool not permitted: ${e.message})"
    } catch (e: IllegalArgumentException) {
        "(tool not permitted: ${e.message})"
    } catch (e: Exception) {
        "(tool error: ${e.message})"
    }
}
