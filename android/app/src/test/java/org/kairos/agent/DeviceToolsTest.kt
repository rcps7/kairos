// SPDX-License-Identifier: GPL-3.0-or-later
// Browser Agent (WebView substitute) and USB serial drivers: protocol encodings, driver control
// sequences against a fake USB transport, and the agent tools with fakes.
package org.kairos.agent

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.browser.*
import org.kairos.agent.serial.*
import java.io.File

class DeviceToolsTest {
    private val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())

    // ---------------- serial ----------------
    private class FakeUsb(val replies: ArrayDeque<ByteArray> = ArrayDeque()) : UsbTransport {
        val controls = mutableListOf<List<Int>>(); val written = java.io.ByteArrayOutputStream()
        var lastData: ByteArray? = null
        override val maxPacket = 64
        override fun control(requestType: Int, request: Int, value: Int, index: Int, data: ByteArray?, timeoutMs: Int): Int {
            controls += listOf(requestType, request, value, index); if (requestType and 0x80 == 0) lastData = data; return data?.size ?: 0
        }
        override fun bulkOut(data: ByteArray, timeoutMs: Int): Int { written.write(data); return data.size }
        override fun bulkIn(buf: ByteArray, timeoutMs: Int): Int {
            val r = replies.removeFirstOrNull() ?: return 0
            r.copyInto(buf); return r.size
        }
    }

    @Test fun chipDetectionAndEncodings() {
        assertEquals(Chip.CP210X, SerialChips.detect(0x10C4, false))
        assertEquals(Chip.CH34X, SerialChips.detect(0x1A86, false))
        assertEquals(Chip.FTDI, SerialChips.detect(0x0403, false))
        assertEquals(Chip.CDC_ACM, SerialChips.detect(0x2E8A, true))
        assertNull(SerialChips.detect(0x1234, false))
        assertArrayEquals(byteArrayOf(0x00, 0xC2.toByte(), 0x01, 0x00, 0, 0, 8), SerialChips.cdcLineCoding(115200))
        assertEquals(0xCC83 to 0x08, SerialChips.ch34xBaud(115200))
        assertEquals(0xB282 to 0x0C, SerialChips.ch34xBaud(9600))
        assertEquals(0xF387 to 0x00, SerialChips.ch34xBaud(921600))
        assertEquals(0x4138 to 0, SerialChips.ftdiDivisor(9600))   // FTDI app note value for 9600
        assertEquals(0x001A to 0, SerialChips.ftdiDivisor(115200))
        val raw = ByteArray(70) { it.toByte() }
        // 2 status bytes per 64-byte packet are dropped
        assertArrayEquals((2 until 64).map { it.toByte() }.toByteArray() + (66 until 70).map { it.toByte() }.toByteArray(),
            SerialChips.ftdiStrip(raw, 70, 64))
    }

    @Test fun driverSequences() {
        val cdc = FakeUsb(); SerialConnection(Chip.CDC_ACM, cdc, 1).configure(115200)
        assertEquals(listOf(listOf(0x21, 0x20, 0, 1), listOf(0x21, 0x22, 3, 1)), cdc.controls)
        val cp = FakeUsb(); SerialConnection(Chip.CP210X, cp).configure(9600)
        assertEquals(listOf(0x00, 0x1E, 0x03, 0x07), cp.controls.map { it[1] })
        val ch = FakeUsb(); SerialConnection(Chip.CH34X, ch).configure(115200)
        assertTrue(ch.controls.contains(listOf(0x40, 0x9A, 0x1312, 0xCC83)))
        assertTrue(ch.controls.contains(listOf(0x40, 0x9A, 0x2518, 0xC3)))
        val ft = FakeUsb(); SerialConnection(Chip.FTDI, ft).configure(9600)
        assertTrue(ft.controls.contains(listOf(0x40, 0x03, 0x4138, 1)))
    }

    @Test fun writeAndReadThroughDriver() {
        val usb = FakeUsb(ArrayDeque(listOf("OK ".toByteArray(), "ready\r\n".toByteArray())))
        val c = SerialConnection(Chip.CDC_ACM, usb)
        assertEquals(200, c.write(ByteArray(200) { 'a'.code.toByte() }))
        assertEquals(200, usb.written.size())
        assertEquals("OK ready\r\n", String(c.read(totalMs = 1000, idleMs = 150)))
        val ft = FakeUsb(ArrayDeque(listOf(byteArrayOf(0x01, 0x60) + "hi".toByteArray())))
        assertEquals("hi", String(SerialConnection(Chip.FTDI, ft).read(500, 100)))
    }

    @Test fun unescape() {
        assertArrayEquals(byteArrayOf('A'.code.toByte(), 13, 10, 0x1B, 92, 'q'.code.toByte()), SerialText.unescape("A\\r\\n\\x1b\\\\q"))
        assertEquals("plain", String(SerialText.unescape("plain")))
    }

    private class FakePorts : SerialPorts {
        val opened = mutableMapOf<String, Int>(); val sent = mutableListOf<String>()
        override fun list() = listOf(PortInfo("/dev/bus/usb/001/002", "ESP32 (10c4:ea60)", Chip.CP210X, true))
        override fun open(id: String, baud: Int): String { opened[id] = baud; return "Opened $id (CP210x) at $baud baud." }
        override fun write(id: String, data: ByteArray): Int { sent += String(data); return data.size }
        override fun read(id: String, totalMs: Long) = "pong\r\n".toByteArray()
        override fun close(id: String) { opened.remove(id) }
        override fun closeAll() = opened.clear()
        override fun isOpen(id: String) = id in opened
    }

    @Test fun serialTools() = runBlocking {
        val ports = FakePorts()
        val t = SerialTools(CharacterRegistry(pack), { ports })
        assertTrue(t.run(ToolCall("serial_list")).contains("ESP32 (10c4:ea60) [CP210x]"))
        assertEquals("pong\r\n", t.run(ToolCall("serial_send", mapOf("device" to "d", "data" to "ping", "baud" to "9600"))))
        assertEquals(9600, ports.opened["d"]); assertEquals(listOf("ping\n"), ports.sent)
        assertEquals("Wrote 3 bytes.", t.run(ToolCall("serial_write", mapOf("device" to "d", "data" to "a\\r\\n"))))
        assertEquals("Closed d.", t.run(ToolCall("serial_close", mapOf("device" to "d"))))
        val denied = SerialTools(CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "x", capabilities = listOf("memory")))).also { it.activeId = "x" }, { ports })
        assertEquals("(tool not permitted: peripherals)", denied.run(ToolCall("serial_list")))
        assertEquals("(unknown tool: other)", t.run(ToolCall("other")))
    }

    // ---------------- browser ----------------
    private class FakePage : BrowserPage {
        override var url = "about:blank"; override var title = ""
        val scripts = mutableListOf<String>(); var captcha = ""
        override suspend fun load(url: String) { this.url = url; title = "Form" }
        override suspend fun eval(js: String): String { scripts += js
            return when {
                js.contains("recaptcha") -> captcha
                js.contains("__kFind(t, true)") -> "clicked button Send"
                js.contains("__kFind(t, false)") && js.contains("setter") -> "filled input#name"
                else -> "# Form\nHello" }
        }
        override suspend fun back() = false
        override suspend fun forward() = false
        override suspend fun reload() {}
        override suspend fun settle(maxMs: Long) {}
        override suspend fun screenshot(file: File): Boolean { file.writeBytes(byteArrayOf(1)); return true }
    }

    @Test fun urlsAndScriptQuoting() {
        val b = BrowserAgent({ FakePage() }, File("build/tmp/shots"))
        assertEquals("https://example.org", b.checkUrl("example.org"))
        assertEquals("http://127.0.0.1:8080/x", b.checkUrl("http://127.0.0.1:8080/x"))
        for (bad in listOf("javascript:alert(1)", "file:///sdcard/x", "intent://x", "content://a", ""))
            assertThrows(IllegalArgumentException::class.java) { b.checkUrl(bad) }
        // Arguments are embedded as JSON string literals, so quotes cannot break out of the script.
        val js = BrowserScripts.fill("a'b\"c", "x');alert(1);//")
        assertTrue(js.contains("(\"a'b\\\"c\", \"x');alert(1);//\")"))
        assertTrue(BrowserScripts.read(null).contains("})(null)"))
    }

    @Test fun browserTools() = runBlocking {
        val page = FakePage()
        val t = BrowserTools(CharacterRegistry(pack), { BrowserAgent({ page }, File("build/tmp/shots")) })
        assertTrue(t.run(ToolCall("browser_goto", mapOf("url" to "example.org"))).startsWith("URL: https://example.org\n# Form"))
        assertEquals("name: filled input#name\nemail: filled input#name",
            t.run(ToolCall("browser_form", mapOf("fields" to """{"name":"Kai","email":"k@x"}"""))))
        assertTrue(t.run(ToolCall("browser_click", mapOf("target" to "Send"))).startsWith("clicked button Send"))
        assertEquals("No CAPTCHA detected on https://example.org.", t.run(ToolCall("browser_captcha")))
        page.captcha = "reCAPTCHA"
        val c = t.run(ToolCall("browser_captcha"))
        assertTrue(c.contains("reCAPTCHA") && c.contains("never solves"))
        assertTrue(t.run(ToolCall("browser_goto", mapOf("url" to "example.org"))).contains("CAPTCHA detected"))
        assertTrue(t.run(ToolCall("browser_screenshot")).startsWith("Screenshot saved:"))
        assertTrue(t.run(ToolCall("browser_action", mapOf("steps" to """[{"op":"fill","target":"name","value":"x"},{"op":"click","target":"Send"}]""")))
            .contains("1. filled input#name\n2. clicked button Send"))
        assertEquals("(browser error: Only http(s) pages can be opened (got 'javascript:').)",
            t.run(ToolCall("browser_goto", mapOf("url" to "javascript:alert(1)"))))
        val denied = BrowserTools(CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "x", capabilities = listOf("memory")))).also { it.activeId = "x" },
            { BrowserAgent({ page }, File("build/tmp/shots")) })
        assertEquals("(tool not permitted: browser_control)", denied.run(ToolCall("browser_goto", mapOf("url" to "a.org"))))
        assertTrue(denied.run(ToolCall("browser_captcha")).contains("reCAPTCHA"))
    }
}
