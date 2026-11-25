// SPDX-License-Identifier: GPL-3.0-or-later
// Web search + scraping (desktop kairos/web/__init__.py) against a local mock server.
package org.kairos.agent

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.web.WebException
import org.kairos.agent.web.WebScraper
import org.kairos.agent.web.WebSearcher

class WebTest {
    private val ddg = """
        <html><body>
        <div class="result results_links result--ad"><a class="result__a" href="https://ads.example">Ad</a></div>
        <div class="result results_links"><h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fkotlinlang.org%2Fdocs%2F&amp;rut=abc">Kotlin Docs</a></h2>
          <a class="result__snippet">Official Kotlin documentation.</a></div>
        <div class="result results_links"><h2><a class="result__a" href="https://developer.android.com/">Android Developers</a></h2>
          <a class="result__snippet">Build apps.</a></div>
        </body></html>""".trimIndent()

    @Test fun parsesDuckDuckGoResultsAndSkipsAds() {
        val r = WebSearcher.parseResults(ddg)
        assertEquals(2, r.size)
        assertEquals("Kotlin Docs", r[0].title)
        assertEquals("https://kotlinlang.org/docs/", r[0].url)
        assertEquals("Official Kotlin documentation.", r[0].description)
        assertEquals(1, WebSearcher.parseResults(ddg, 1).size)
        assertTrue(WebSearcher.format(r).startsWith("1. Kotlin Docs — https://kotlinlang.org/docs/"))
    }

    @Test fun searchPostsQuery() = runTest {
        val s = MockWebServer(); s.enqueue(MockResponse().setBody(ddg)); s.start()
        val r = WebSearcher(endpoint = s.url("/html/").toString()).search("kotlin docs")
        assertEquals(2, r.size)
        val req = s.takeRequest()
        assertEquals("POST", req.method); val body = req.body.readUtf8(); assertTrue(body, body == "q=kotlin%20docs" || body == "q=kotlin+docs")
        s.shutdown()
    }

    @Test fun scraperCleansPageAndRetriesOn403() = runTest {
        val s = MockWebServer()
        s.enqueue(MockResponse().setResponseCode(403))
        s.enqueue(MockResponse().setBody("<html><head><title>T</title><script>evil()</script></head><body><nav>menu</nav><p>Hello world</p><footer>f</footer></body></html>"))
        s.start()
        val p = WebScraper().fetch(s.url("/p").toString())
        assertEquals("T", p.title)
        assertTrue(p.text.contains("Hello world"))
        assertFalse(p.text.contains("evil")); assertFalse(p.text.contains("menu")); assertFalse(p.text.contains("f\n"))
        assertEquals(2, s.requestCount)
        // Second attempt used a different browser header set (desktop rotation).
        s.takeRequest(); assertTrue(s.takeRequest().getHeader("User-Agent")!!.contains("Macintosh"))
        s.shutdown()
    }

    @Test fun scraperGivesUpAfterAllVariantsBlocked() = runTest {
        val s = MockWebServer(); repeat(3) { s.enqueue(MockResponse().setResponseCode(403)) }; s.start()
        val e = runCatching { WebScraper().fetch(s.url("/").toString()) }.exceptionOrNull()
        assertTrue(e is WebException && e.message!!.contains("403"))
        s.shutdown()
    }

    @Test fun scraperRejectsNonHttp() = runTest {
        assertTrue(runCatching { WebScraper().fetch("file:///etc/passwd") }.exceptionOrNull() is WebException)
    }
}
