// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. The single WebView the agent and the Browser screen share.
package org.kairos.agent.browser

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

class WebViewPage(private val context: Context) : BrowserPage {
    private var web: WebView? = null
    @Volatile private var loading = false
    @Volatile private var lastStart = 0L
    private var done = CompletableDeferred<Unit>().also { it.complete(Unit) }
    private val _state = MutableStateFlow("about:blank")
    /** Current URL, for the Browser screen's address bar. */
    val urlFlow: StateFlow<String> = _state

    @Volatile override var url: String = "about:blank"; private set
    @Volatile override var title: String = ""; private set

    /** The WebView (main thread only). */
    @SuppressLint("SetJavaScriptEnabled")
    fun view(): WebView = web ?: WebView(context).also { w ->
        w.settings.javaScriptEnabled = true
        w.settings.domStorageEnabled = true
        w.settings.allowFileAccess = false
        w.settings.allowContentAccess = false
        w.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                val s = req.url.scheme?.lowercase()
                return !(s == "http" || s == "https" || s == "about" || s == "data")
            }
            override fun onPageStarted(view: WebView, u: String, favicon: Bitmap?) {
                loading = true; lastStart = System.currentTimeMillis()
                if (done.isCompleted) done = CompletableDeferred()
                url = u; _state.value = u
            }
            override fun onPageFinished(view: WebView, u: String) {
                loading = false; url = u; title = view.title.orEmpty(); _state.value = u; done.complete(Unit)
            }
        }
        if (w.width == 0) { w.measure(View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(1920, View.MeasureSpec.EXACTLY)); w.layout(0, 0, 1080, 1920) }
        web = w
    }

    override suspend fun load(url: String) {
        withContext(Dispatchers.Main) {
            val w = view(); done = CompletableDeferred(); loading = true; lastStart = System.currentTimeMillis(); w.loadUrl(url)
        }
        waitDone(30_000)
    }

    private suspend fun waitDone(ms: Long) {
        withTimeoutOrNull(ms) { done.await() }
        delay(150)
    }

    override suspend fun settle(maxMs: Long) {
        val start = System.currentTimeMillis()
        delay(400)
        if (loading || lastStart >= start) waitDone(maxMs)
    }

    override suspend fun eval(js: String): String = withContext(Dispatchers.Main) {
        val r = CompletableDeferred<String?>()
        view().evaluateJavascript(js) { r.complete(it) }
        val raw = withTimeoutOrNull(15_000) { r.await() } ?: return@withContext "(script timed out)"
        when (val e = runCatching { Json.parseToJsonElement(raw) }.getOrNull()) {
            null, JsonNull -> ""
            is JsonPrimitive -> e.content
            else -> e.toString()
        }
    }

    override suspend fun back(): Boolean = withContext(Dispatchers.Main) {
        val w = view(); if (w.canGoBack()) { w.goBack(); true } else false
    }.also { if (it) settle() }

    override suspend fun forward(): Boolean = withContext(Dispatchers.Main) {
        val w = view(); if (w.canGoForward()) { w.goForward(); true } else false
    }.also { if (it) settle() }

    override suspend fun reload() { withContext(Dispatchers.Main) { view().reload() }; settle() }

    override suspend fun screenshot(file: File): Boolean = withContext(Dispatchers.Main) {
        val w = view()
        val wd = w.width.takeIf { it > 0 } ?: 1080; val ht = w.height.takeIf { it > 0 } ?: 1920
        runCatching {
            val bmp = Bitmap.createBitmap(wd, ht, Bitmap.Config.ARGB_8888)
            w.draw(Canvas(bmp))
            withContext(Dispatchers.IO) { file.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) } }
            true
        }.getOrDefault(false)
    }
}
