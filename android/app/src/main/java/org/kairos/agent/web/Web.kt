// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/web/__init__.py.
// Desktop uses the Python ddgs library; Android queries DuckDuckGo's HTML endpoint (no API key) and parses
// it with Jsoup (MIT), which also replaces BeautifulSoup for page cleaning.
package org.kairos.agent.web

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.net.URLDecoder
import java.util.concurrent.TimeUnit

data class SearchResult(val title: String, val url: String, val description: String)
data class Page(val title: String, val text: String, val html: String)

class WebException(msg: String) : RuntimeException(msg)

private const val UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

val BROWSER_HEADER_VARIANTS: List<Map<String, String>> = listOf(
    mapOf("User-Agent" to UA,
        "Accept" to "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language" to "en-US,en;q=0.9", "Referer" to "https://www.google.com/", "DNT" to "1",
        "Upgrade-Insecure-Requests" to "1"),
    mapOf("User-Agent" to "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Accept" to "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language" to "en-GB,en;q=0.8", "Referer" to "https://www.bing.com/", "DNT" to "1",
        "Upgrade-Insecure-Requests" to "1"),
    mapOf("User-Agent" to "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept" to "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language" to "en-US,en;q=0.5", "Referer" to "https://duckduckgo.com/", "DNT" to "1",
        "Upgrade-Insecure-Requests" to "1"),
)

private fun defaultHttp() = OkHttpClient.Builder().connectTimeout(20, TimeUnit.SECONDS)
    .readTimeout(30, TimeUnit.SECONDS).followRedirects(true).build()

class WebSearcher(
    private val http: OkHttpClient = defaultHttp(),
    private val endpoint: String = "https://html.duckduckgo.com/html/",
) {
    suspend fun search(query: String, maxResults: Int = 10): List<SearchResult> = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(endpoint)
            .apply { BROWSER_HEADER_VARIANTS[0].forEach { (k, v) -> header(k, v) } }
            .post(FormBody.Builder().add("q", query).build()).build()
        http.newCall(req).execute().use { r ->
            if (r.code >= 400) throw WebException("Search failed: HTTP ${r.code}")
            parseResults(r.body?.string().orEmpty(), maxResults)
        }
    }

    companion object {
        /** Parse DuckDuckGo HTML results; unwraps //duckduckgo.com/l/?uddg= redirect links. */
        fun parseResults(html: String, maxResults: Int = 10): List<SearchResult> {
            val doc = Jsoup.parse(html)
            val out = mutableListOf<SearchResult>()
            for (res in doc.select("div.result, div.web-result")) {
                if (res.hasClass("result--ad")) continue
                val a = res.selectFirst("a.result__a") ?: continue
                val title = a.text().trim()
                val href = unwrap(a.attr("href"))
                val desc = res.selectFirst(".result__snippet")?.text()?.trim().orEmpty()
                if (title.isEmpty() && href.isEmpty()) continue
                out += SearchResult(title, href, desc)
                if (out.size >= maxResults) break
            }
            return out
        }

        fun unwrap(href: String): String {
            val i = href.indexOf("uddg=")
            if (i < 0) return if (href.startsWith("//")) "https:$href" else href
            val enc = href.substring(i + 5).substringBefore('&')
            return URLDecoder.decode(enc, "UTF-8")
        }

        fun format(results: List<SearchResult>, max: Int = 8): String =
            results.take(max).mapIndexed { i, r -> "${i + 1}. ${r.title.ifBlank { "Untitled" }} — ${r.url}\n   ${r.description.trim()}" }
                .joinToString("\n")
    }
}

class WebScraper(private val http: OkHttpClient = defaultHttp()) {
    /** GET a page, retrying with different browser headers on 403 (desktop behaviour). */
    suspend fun fetch(url: String): Page = withContext(Dispatchers.IO) {
        if (!url.startsWith("http://") && !url.startsWith("https://")) throw WebException("Only http(s) URLs are supported.")
        var last = 0
        for (h in BROWSER_HEADER_VARIANTS) {
            val req = Request.Builder().url(url).apply { h.forEach { (k, v) -> header(k, v) } }.get().build()
            http.newCall(req).execute().use { r ->
                last = r.code
                if (r.code == 403) return@use
                if (r.code >= 400) throw WebException("HTTP ${r.code} for $url")
                val html = r.body?.string().orEmpty()
                return@withContext clean(html, url)
            }
        }
        throw WebException("Site returned $last Forbidden (blocked). Try another URL or open it in the in-app browser.")
    }

    companion object {
        fun clean(html: String, url: String): Page {
            val doc = Jsoup.parse(html, url)
            doc.select("script, style, noscript, iframe, header, footer, nav").remove()
            val title = doc.title().trim().ifEmpty { url }
            val body = doc.body() ?: return Page(title, "", html)
            // Desktop uses get_text(separator="\n"): one line per block of text.
            val text = body.select("*").filter { it.ownText().isNotBlank() }
                .joinToString("\n") { it.ownText().trim() }
            return Page(title, text, html)
        }
    }
}

fun summarizePrompt(text: String, maxChars: Int = 6000): String =
    "Summarize the following content into clean, easy-to-learn bullet points. " +
        "Use short, clear bullets (one key idea per bullet).\n\nCONTENT:\n${text.take(maxChars)}"
