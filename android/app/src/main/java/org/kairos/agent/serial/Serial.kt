// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Serial peripherals over USB OTG (desktop: peripherals/
// serial_manager.py with pyserial). Small built-in drivers for the common chips on ESP32, Arduino and
// Pico boards — CDC-ACM, Silicon Labs CP210x, WCH CH34x and FTDI — written against Android's
// USB host API, so no extra library is needed.
package org.kairos.agent.serial

import java.io.ByteArrayOutputStream

/** The few USB operations a driver needs; [AndroidUsbTransport] implements it with UsbDeviceConnection. */
interface UsbTransport {
    val maxPacket: Int
    fun control(requestType: Int, request: Int, value: Int, index: Int, data: ByteArray?, timeoutMs: Int = 1000): Int
    fun bulkOut(data: ByteArray, timeoutMs: Int): Int
    fun bulkIn(buf: ByteArray, timeoutMs: Int): Int
}

enum class Chip(val label: String) { CDC_ACM("CDC-ACM"), CP210X("CP210x"), CH34X("CH34x"), FTDI("FTDI") }

object SerialChips {
    const val VID_SILABS = 0x10C4
    const val VID_WCH = 0x1A86
    const val VID_FTDI = 0x0403

    fun detect(vendorId: Int, hasCdcData: Boolean): Chip? = when (vendorId) {
        VID_SILABS -> Chip.CP210X
        VID_WCH -> Chip.CH34X
        VID_FTDI -> Chip.FTDI
        else -> if (hasCdcData) Chip.CDC_ACM else null
    }

    /** CDC SET_LINE_CODING payload: baud (LE32), 1 stop bit, no parity, 8 data bits. */
    fun cdcLineCoding(baud: Int) = byteArrayOf(
        (baud and 0xff).toByte(), (baud shr 8 and 0xff).toByte(), (baud shr 16 and 0xff).toByte(), (baud shr 24 and 0xff).toByte(), 0, 0, 8)

    /** CH34x baud registers (value for 0x1312, value for 0x0f2c), as in the Linux/usb-serial drivers. */
    fun ch34xBaud(baud: Int): Pair<Int, Int> {
        require(baud > 0) { "bad baud rate" }
        var factor: Long; var divisor: Int
        if (baud == 921600) { divisor = 7; factor = 0xf300 } else {
            factor = 1532620800L / baud; divisor = 3
            while (factor > 0xfff0 && divisor > 0) { factor = factor shr 3; divisor-- }
            require(factor <= 0xfff0) { "unsupported baud rate $baud" }
            factor = 0x10000 - factor
        }
        divisor = divisor or 0x80
        return ((factor and 0xff00).toInt() or divisor) to (factor and 0xff).toInt()
    }

    /** FTDI (FT232R/FT-X) baud divisor as (wValue, wIndex high bits) for a 3 MHz base clock. */
    fun ftdiDivisor(baud: Int): Pair<Int, Int> {
        require(baud > 0) { "bad baud rate" }
        if (baud >= 3_000_000) return 0 to 0
        if (baud >= 2_000_000) return 1 to 0
        val eighths = Math.round(3_000_000.0 * 8 / baud).toInt()
        val whole = eighths / 8
        val code = intArrayOf(0, 3, 2, 4, 1, 5, 6, 7)[eighths % 8]
        require(whole in 2..0x3fff) { "unsupported baud rate $baud" }
        return (whole or ((code and 3) shl 14)) to (code shr 2)
    }

    /** FTDI prepends 2 status bytes to every max-packet chunk of an IN transfer. */
    fun ftdiStrip(buf: ByteArray, len: Int, maxPacket: Int): ByteArray {
        val out = ByteArrayOutputStream()
        var i = 0
        while (i < len) {
            val end = minOf(i + maxPacket, len)
            if (end - i > 2) out.write(buf, i + 2, end - i - 2)
            i += maxPacket
        }
        return out.toByteArray()
    }
}

/** An open serial port on one chip. [iface] is the USB interface number (control interface for CDC). */
class SerialConnection(val chip: Chip, private val t: UsbTransport, private val iface: Int = 0) {
    private val outV = 0x40; private val inV = 0xC0

    fun configure(baud: Int) {
        when (chip) {
            Chip.CDC_ACM -> {
                t.control(0x21, 0x20, 0, iface, SerialChips.cdcLineCoding(baud))      // SET_LINE_CODING
                t.control(0x21, 0x22, 0x03, iface, null)                               // DTR | RTS
            }
            Chip.CP210X -> {
                t.control(0x41, 0x00, 0x0001, iface, null)                             // IFC_ENABLE
                t.control(0x41, 0x1E, 0, iface, byteArrayOf((baud and 0xff).toByte(), (baud shr 8 and 0xff).toByte(),
                    (baud shr 16 and 0xff).toByte(), (baud shr 24 and 0xff).toByte()))  // SET_BAUDRATE
                t.control(0x41, 0x03, 0x0800, iface, null)                             // SET_LINE_CTL 8N1
                t.control(0x41, 0x07, 0x0303, iface, null)                             // SET_MHS DTR/RTS
            }
            Chip.CH34X -> {
                t.control(inV, 0x5F, 0, 0, ByteArray(2))                               // read version
                t.control(outV, 0xA1, 0, 0, null)                                      // serial init
                setCh34xBaud(baud)
                t.control(inV, 0x95, 0x2518, 0, ByteArray(2))
                t.control(outV, 0x9A, 0x2518, 0xC3, null)                              // LCR: RX/TX on, 8N1
                t.control(inV, 0x95, 0x0706, 0, ByteArray(2))
                t.control(outV, 0xA1, 0x501F, 0xD90A, null)
                setCh34xBaud(baud)
                t.control(outV, 0xA4, (0x20 or 0x40).inv() and 0xffff, 0, null)       // DTR/RTS on (active low)
            }
            Chip.FTDI -> {
                val port = iface + 1
                t.control(outV, 0x00, 0, port, null)                                   // reset
                val (v, hi) = SerialChips.ftdiDivisor(baud)
                t.control(outV, 0x03, v, (hi shl 8) or port, null)                     // set baud
                t.control(outV, 0x04, 0x0008, port, null)                              // 8N1
                t.control(outV, 0x01, 0x0303, port, null)                              // DTR/RTS
                t.control(outV, 0x09, 1, port, null)                                   // 1 ms latency
            }
        }
    }

    private fun setCh34xBaud(baud: Int) {
        val (a, b) = SerialChips.ch34xBaud(baud)
        t.control(outV, 0x9A, 0x1312, a, null)
        t.control(outV, 0x9A, 0x0F2C, b, null)
    }

    fun write(data: ByteArray, timeoutMs: Int = 2000): Int {
        var off = 0
        while (off < data.size) {
            val chunk = data.copyOfRange(off, minOf(off + t.maxPacket.coerceAtLeast(16), data.size))
            val n = t.bulkOut(chunk, timeoutMs)
            if (n <= 0) throw java.io.IOException("USB write failed")
            off += n
        }
        return off
    }

    /** One read (up to a few packets); empty when nothing arrives within [timeoutMs]. */
    fun readOnce(timeoutMs: Int): ByteArray {
        val buf = ByteArray(t.maxPacket.coerceAtLeast(64) * 4)
        val n = t.bulkIn(buf, timeoutMs)
        if (n <= 0) return ByteArray(0)
        return if (chip == Chip.FTDI) SerialChips.ftdiStrip(buf, n, t.maxPacket.coerceAtLeast(64)) else buf.copyOf(n)
    }

    /** Collect bytes until [totalMs] passes or the line is quiet for [idleMs] after some data. */
    fun read(totalMs: Long = 1500, idleMs: Long = 250, max: Int = 64_000): ByteArray {
        val out = ByteArrayOutputStream()
        val end = System.currentTimeMillis() + totalMs
        var quietSince = System.currentTimeMillis()
        while (System.currentTimeMillis() < end && out.size() < max) {
            val b = readOnce(100)
            if (b.isNotEmpty()) { out.write(b); quietSince = System.currentTimeMillis() }
            else if (out.size() > 0 && System.currentTimeMillis() - quietSince >= idleMs) break
        }
        return out.toByteArray()
    }
}

data class PortInfo(val id: String, val description: String, val chip: Chip?, val permitted: Boolean)

/** Port registry the tools and UI use (desktop SerialManager). */
interface SerialPorts {
    fun list(): List<PortInfo>
    /** Opens (or reuses) the port; returns a status line. May ask the user for USB permission. */
    fun open(id: String, baud: Int): String
    fun write(id: String, data: ByteArray): Int
    fun read(id: String, totalMs: Long = 1500): ByteArray
    fun close(id: String)
    fun closeAll()
    fun isOpen(id: String): Boolean
}

/** Tool-facing helpers (shared with the Serial screen). */
object SerialText {
    /** "\n", "\r", "\t" and "\xNN" escapes, so the agent can send line endings and raw bytes. */
    fun unescape(s: String): ByteArray {
        val out = ByteArrayOutputStream(); var i = 0
        while (i < s.length) {
            val c = s[i]
            val nx = if (c == '\\' && i + 1 < s.length) s[i + 1] else ' '
            val hex = if (nx == 'x' && i + 4 <= s.length) s.substring(i + 2, i + 4).toIntOrNull(16) else null
            when {
                c != '\\' || i + 1 >= s.length -> { out.write(c.toString().toByteArray()); i++ }
                nx == 'n' -> { out.write(10); i += 2 }
                nx == 'r' -> { out.write(13); i += 2 }
                nx == 't' -> { out.write(9); i += 2 }
                nx == '\\' -> { out.write(92); i += 2 }
                hex != null -> { out.write(hex); i += 4 }
                else -> { out.write(92); i++ }
            }
        }
        return out.toByteArray()
    }

    fun show(b: ByteArray): String = String(b, Charsets.UTF_8).replace("\u0000", "")
}
