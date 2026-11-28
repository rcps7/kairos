// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Browser Agent substitute (desktop kairos/browser.py, Playwright):
// an in-app Android WebView driven by DOM scripts. CAPTCHAs are detected and handed to the user —
// there is no automated solving.
package org.kairos.agent.browser

import kotlinx.serialization.json.*
import java.io.File

/** What the agent needs from a page. The Android implementation is [WebViewPage]. */
interface BrowserPage {
    val url: String
    val title: String
    /** Navigate and wait for the page to finish loading. */
    suspend fun load(url: String)
    /** Evaluate a JS expression; returns its value as a string (JSON for objects). */
    suspend fun eval(js: String): String
    suspend fun back(): Boolean
    suspend fun forward(): Boolean
    suspend fun reload()
    /** Wait for a navigation that a click or key may have started. */
    suspend fun settle(maxMs: Long = 6000)
    suspend fun screenshot(file: File): Boolean
}

object BrowserScripts {
    private fun q(s: String?): String = if (s == null) "null" else JsonPrimitive(s).toString()

    /** Find by CSS selector, label text, name/id/placeholder/aria-label, or (for clicks) visible text. */
    private const val FIND = """
function __kFind(t, clickable) {
  try { var e = document.querySelector(t); if (e) return e; } catch (x) {}
  var low = String(t).trim().toLowerCase();
  var labels = document.querySelectorAll('label');
  for (var i = 0; i < labels.length; i++) {
    if (labels[i].innerText.trim().replace(/[:*]$/, '').trim().toLowerCase() === low.replace(/[:*]$/, '')) {
      var f = labels[i].htmlFor ? document.getElementById(labels[i].htmlFor) : labels[i].querySelector('input,textarea,select');
      if (f) return f;
    }
  }
  var els = document.querySelectorAll('input,textarea,select,button,a,[role=button],[onclick],[contenteditable="true"],summary');
  var pass = clickable ? 2 : 1;
  for (var p = 0; p < pass; p++) for (var i = 0; i < els.length; i++) {
    var e = els[i];
    var keys = [e.name, e.id, e.placeholder, e.getAttribute('aria-label'), e.title];
    if (clickable) { keys.push(e.innerText); if (e.type === 'submit' || e.type === 'button') keys.push(e.value); }
    for (var k = 0; k < keys.length; k++) {
      var v = keys[k] ? String(keys[k]).trim().toLowerCase() : '';
      if (v && (p === 0 ? v === low : v.indexOf(low) >= 0)) return e;
    }
  }
  return null;
}
function __kDesc(e) { return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.name ? '[name=' + e.name + ']' : ''); }
"""

    fun read(selector: String?) = """(function(sel){
  var e = sel ? document.querySelector(sel) : document.body;
  if (!e) return 'NOT_FOUND: ' + sel;
  return (sel ? '' : (document.title ? '# ' + document.title + '\n' : '')) + (e.innerText || e.value || '');
})(${q(selector)})"""

    fun forms() = """(function(){
  var out = [];
  var els = document.querySelectorAll('input,textarea,select,[contenteditable="true"]');
  for (var i = 0; i < els.length && out.length < 80; i++) {
    var e = els[i]; var t = (e.type || e.tagName).toLowerCase();
    if (t === 'hidden') continue;
    var lab = '';
    if (e.id) { var l = document.querySelector('label[for="' + e.id + '"]'); if (l) lab = l.innerText.trim(); }
    if (!lab && e.closest && e.closest('label')) lab = e.closest('label').innerText.trim();
    var r = e.getBoundingClientRect();
    // Values are masked by default: page text is sent to the LLM, so never leak
    // typed secrets. Checkbox/radio state and select options are safe to show.
    var safeValue = (t === 'checkbox' || t === 'radio') ? String(e.checked)
      : (t === 'select' ? String(e.value || '').slice(0, 80) : (e.isContentEditable ? (e.innerText ? '***' : '') : (e.value ? '***' : '')));
    out.push({tag: e.tagName.toLowerCase(), type: t, name: e.name || '', id: e.id || '', label: lab,
      placeholder: e.placeholder || '', value: safeValue,
      rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}});
  }
  return JSON.stringify(out);
})()"""

    fun fill(target: String, value: String) = FIND + """(function(t, v){
  var e = __kFind(t, false);
  if (!e) return 'NOT_FOUND: ' + t;
  e.focus();
  var type = (e.type || '').toLowerCase();
  if (type === 'checkbox' || type === 'radio') { e.checked = /^(1|true|yes|on|checked)$/i.test(v); }
  else if (e.tagName === 'SELECT') {
    var ok = false;
    for (var i = 0; i < e.options.length; i++) { var o = e.options[i];
      if (o.value === v || o.text.trim().toLowerCase() === v.trim().toLowerCase()) { e.selectedIndex = i; ok = true; break; } }
    if (!ok) return 'NO_OPTION: ' + v;
  } else if (e.isContentEditable) {
    e.innerText = v;
  } else {
    var proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value').set; setter.call(e, v);
  }
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
  return 'filled ' + __kDesc(e);
})(${q(target)}, ${q(value)})"""

    fun click(target: String) = FIND + """(function(t){
  var e = __kFind(t, true);
  if (!e) return 'NOT_FOUND: ' + t;
  e.scrollIntoView({block: 'center'}); e.click();
  return 'clicked ' + __kDesc(e) + ' ' + (e.innerText || e.value || '').trim().slice(0, 60);
})(${q(target)})"""

    fun clickAt(x: Int, y: Int) = """(function(x, y){
  var dpr = window.devicePixelRatio || 1;
  var cx = x / dpr, cy = y / dpr;
  var e = document.elementFromPoint(cx, cy);
  if (!e) return 'NOT_FOUND: nothing at ' + Math.round(cx) + ',' + Math.round(cy);
  ['mousedown', 'mouseup'].forEach(function(n){ e.dispatchEvent(new MouseEvent(n, {bubbles: true, clientX: cx, clientY: cy})); });
  e.click(); return 'clicked ' + e.tagName.toLowerCase() + ' at ' + Math.round(cx) + ',' + Math.round(cy);
})($x, $y)"""

    fun key(target: String?, key: String) = FIND + """(function(t, k){
  var e = t ? __kFind(t, false) : (document.activeElement || document.body);
  if (!e) return 'NOT_FOUND: ' + t;
  ['keydown', 'keypress', 'keyup'].forEach(function(n){ e.dispatchEvent(new KeyboardEvent(n, {key: k, bubbles: true})); });
  if (k === 'Enter' && e.form) { if (e.form.requestSubmit) e.form.requestSubmit(); else e.form.submit(); return 'submitted form'; }
  return 'pressed ' + k;
})(${q(target)}, ${q(key)})"""

    fun drag(from: String, to: String) = FIND + """(function(a, b){
  var s = __kFind(a, true), d = __kFind(b, true);
  if (!s || !d) return 'NOT_FOUND: ' + (s ? b : a);
  var dt = new DataTransfer();
  s.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: dt}));
  d.dispatchEvent(new DragEvent('dragenter', {bubbles: true, dataTransfer: dt}));
  d.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));
  d.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
  s.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
  return 'dragged ' + __kDesc(s) + ' to ' + __kDesc(d);
})(${q(from)}, ${q(to)})"""

    fun scroll(dy: Int) = "(function(){ window.scrollBy(0, $dy); return 'scrolled to ' + Math.round(window.scrollY); })()"

    fun captcha() = """(function(){
  var hits = [];
  var sels = {'reCAPTCHA': 'iframe[src*="recaptcha"],.g-recaptcha', 'hCaptcha': 'iframe[src*="hcaptcha"],.h-captcha',
    'Cloudflare Turnstile': 'iframe[src*="challenges.cloudflare"],.cf-turnstile', 'Generic captcha': 'img[src*="captcha" i],input[name*="captcha" i]'};
  for (var k in sels) if (document.querySelector(sels[k])) hits.push(k);
  return hits.join(', ');
})()"""
}

/** Agent-facing browser operations with the desktop tool names. */
class BrowserAgent(private val page: () -> BrowserPage, private val shotsDir: File) {
    private val maxText = 6000

    fun checkUrl(raw: String): String {
        var u = raw.trim()
        if (u.isEmpty()) throw IllegalArgumentException("url is required")
        if (!Regex("^[a-zA-Z][a-zA-Z0-9+.-]*:").containsMatchIn(u)) u = "https://$u"
        val scheme = u.substringBefore(':').lowercase()
        require(scheme == "http" || scheme == "https" || u == "about:blank") { "Only http(s) pages can be opened (got '$scheme:')." }
        return u
    }

    private suspend fun summary(): String {
        val p = page()
        val text = p.eval(BrowserScripts.read(null))
        val cap = p.eval(BrowserScripts.captcha())
        return "URL: ${p.url}\n" + text.take(maxText) + (if (text.length > maxText) "\n…(truncated)" else "") + captchaNote(cap)
    }

    private fun captchaNote(found: String) = if (found.isBlank()) "" else
        "\n\n[CAPTCHA detected: $found. Ask the user to solve it in the Browser screen, then continue. Kairos never solves CAPTCHAs automatically.]"

    suspend fun goto(url: String): String { page().load(checkUrl(url)); return summary() }
    suspend fun read(selector: String?): String {
        val t = page().eval(BrowserScripts.read(selector?.takeIf { it.isNotBlank() }))
        return t.take(maxText)
    }
    suspend fun forms(): String = page().eval(BrowserScripts.forms())
    suspend fun fill(target: String, value: String): String = page().eval(BrowserScripts.fill(target, value))
    suspend fun form(fields: Map<String, String>): String {
        val out = StringBuilder()
        for ((k, v) in fields.entries) {
            if (out.isNotEmpty()) out.append('\n')
            out.append(k).append(": ").append(fill(k, v))
        }
        return out.toString()
    }
    suspend fun click(target: String): String {
        val r = page().eval(BrowserScripts.click(target)); page().settle(); return "$r\nNow at: ${page().url}"
    }
    suspend fun mouse(x: Int, y: Int): String { val r = page().eval(BrowserScripts.clickAt(x, y)); page().settle(); return r }
    suspend fun key(target: String?, key: String): String {
        val r = page().eval(BrowserScripts.key(target?.takeIf { it.isNotBlank() }, key)); page().settle(); return "$r\nNow at: ${page().url}"
    }
    suspend fun js(code: String): String = page().eval(code).take(maxText)
    suspend fun back(): String = if (page().back()) summary() else "(no page to go back to)"
    suspend fun forward(): String = if (page().forward()) summary() else "(no page to go forward to)"
    suspend fun reload(): String { page().reload(); return summary() }
    suspend fun captcha(): String = page().eval(BrowserScripts.captcha()).let {
        if (it.isBlank()) "No CAPTCHA detected on ${page().url}." else captchaNote(it).trim()
    }
    suspend fun screenshot(): String {
        shotsDir.mkdirs()
        val f = File(shotsDir, "shot-${System.currentTimeMillis()}.png")
        return if (page().screenshot(f)) "Screenshot saved: ${f.path}" else "(screenshot failed)"
    }

    /** browser_action: a list of steps like [{"op":"click","target":"Send"},{"op":"type",...}]. */
    suspend fun actions(stepsJson: String): String {
        val steps = runCatching { Json.parseToJsonElement(stepsJson).jsonArray }.getOrNull()
            ?: return "(browser_action: steps must be a JSON list)"
        return steps.take(MAX_ACTIONS).mapIndexed { i, s ->
            val r = try {
                val o = s.jsonObject
                fun a(k: String) = o[k]?.jsonPrimitive?.contentOrNull
                when (a("op")) {
                    "goto" -> { page().load(checkUrl(a("url").orEmpty())); "opened ${page().url}" }
                    "click" -> click(a("target").orEmpty())
                    "fill", "type" -> fill(a("target").orEmpty(), a("value") ?: a("text").orEmpty())
                    "key" -> key(a("target"), a("key") ?: "Enter")
                    "drag" -> page().eval(BrowserScripts.drag(a("from").orEmpty(), a("to").orEmpty()))
                    "scroll" -> page().eval(BrowserScripts.scroll(a("dy")?.toIntOrNull() ?: 600))
                    "wait" -> { kotlinx.coroutines.delay((a("ms")?.toLongOrNull() ?: 1000).coerceAtMost(15000)); "waited" }
                    "text", "read" -> read(a("target") ?: a("selector"))
                    "screenshot" -> screenshot()
                    else -> "unknown op '${a("op")}'"
                }
            } catch (e: Exception) { "error: ${e.message}" }
            "${i + 1}. $r"
        }.joinToString("\n")
    }

    private companion object {
        /** Cap a single browser_action list so a runaway model cannot loop forever. */
        const val MAX_ACTIONS = 50
    }
}
