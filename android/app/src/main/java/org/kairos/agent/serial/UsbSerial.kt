// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Android USB host side of the serial drivers.
package org.kairos.agent.serial

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import androidx.core.content.ContextCompat
import java.util.Locale

class AndroidUsbTransport(private val conn: UsbDeviceConnection, private val epIn: UsbEndpoint, private val epOut: UsbEndpoint) : UsbTransport {
    override val maxPacket: Int get() = epIn.maxPacketSize
    override fun control(requestType: Int, request: Int, value: Int, index: Int, data: ByteArray?, timeoutMs: Int): Int =
        conn.controlTransfer(requestType, request, value, index, data, data?.size ?: 0, timeoutMs)
    override fun bulkOut(data: ByteArray, timeoutMs: Int): Int = conn.bulkTransfer(epOut, data, data.size, timeoutMs)
    override fun bulkIn(buf: ByteArray, timeoutMs: Int): Int = conn.bulkTransfer(epIn, buf, buf.size, timeoutMs)
}

class UsbSerialPorts(private val context: Context) : SerialPorts {
    private val usb = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private class Open(val conn: UsbDeviceConnection, val ifaces: List<UsbInterface>, val port: SerialConnection)
    private val open = mutableMapOf<String, Open>()

    private fun dataInterface(d: UsbDevice): UsbInterface? =
        (0 until d.interfaceCount).map { d.getInterface(it) }.firstOrNull { i ->
            (0 until i.endpointCount).map { i.getEndpoint(it) }.let { eps ->
                eps.any { it.type == UsbConstants.USB_ENDPOINT_XFER_BULK && it.direction == UsbConstants.USB_DIR_IN } &&
                    eps.any { it.type == UsbConstants.USB_ENDPOINT_XFER_BULK && it.direction == UsbConstants.USB_DIR_OUT }
            }
        }

    private fun chipOf(d: UsbDevice): Chip? {
        val data = dataInterface(d)
        return SerialChips.detect(d.vendorId, data?.interfaceClass == UsbConstants.USB_CLASS_CDC_DATA ||
            (0 until d.interfaceCount).any { d.getInterface(it).interfaceClass == UsbConstants.USB_CLASS_COMM })
    }

    private fun vidpid(d: UsbDevice) = String.format(Locale.US, "%04x:%04x", d.vendorId, d.productId)

    override fun list(): List<PortInfo> = usb.deviceList.values.sortedBy { it.deviceName }.map { d ->
        val name = listOfNotNull(d.manufacturerName.takeIf { usb.hasPermission(d) }, d.productName.takeIf { usb.hasPermission(d) })
            .joinToString(" ").ifBlank { "USB device" }
        PortInfo(d.deviceName, "$name (${vidpid(d)})", chipOf(d), usb.hasPermission(d))
    }.filter { it.chip != null }

    private fun device(id: String): UsbDevice =
        usb.deviceList.values.firstOrNull { it.deviceName == id || vidpid(it) == id.lowercase(Locale.US) }
            ?: list().getOrNull(id.toIntOrNull() ?: -1)?.let { p -> usb.deviceList[p.id] }
            ?: throw IllegalArgumentException("No USB serial device '$id'. Use serial_list.")

    private fun requestPermission(d: UsbDevice) {
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        val pi = PendingIntent.getBroadcast(
            context, 0,
            Intent(ACTION_PERMISSION).setPackage(context.packageName),
            flags or PendingIntent.FLAG_UPDATE_CURRENT)
        usb.requestPermission(d, pi)
    }

    /** Consumes the USB permission result and closes ports when a device is unplugged. */
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context?, intent: Intent?) {
            val i = intent ?: return
            when (i.action) {
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    @Suppress("DEPRECATION")
                    val d: UsbDevice? = i.getParcelableExtra(UsbManager.EXTRA_DEVICE)
                    d?.let { close(it.deviceName) }
                }
                ACTION_PERMISSION -> {
                    // Answer consumed; the Serial screen refreshes and the user taps Connect again.
                }
            }
        }
    }

    init {
        val filter = IntentFilter().apply {
            addAction(ACTION_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        runCatching { ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED) }
    }

    @Synchronized
    override fun open(id: String, baud: Int): String {
        val d = device(id)
        open[d.deviceName]?.let { it.port.configure(baud); return "Port ${d.deviceName} re-configured at $baud baud." }
        if (!usb.hasPermission(d)) { requestPermission(d); return "Approve USB access in the dialog on the phone, then retry." }
        val chip = chipOf(d) ?: throw IllegalArgumentException("Unsupported USB device (not a known serial chip).")
        val data = dataInterface(d) ?: throw IllegalArgumentException("No bulk endpoints on this device.")
        val conn = usb.openDevice(d) ?: throw IllegalStateException("Could not open the USB device.")
        val claimed = mutableListOf<UsbInterface>()
        val control = if (chip == Chip.CDC_ACM) (0 until d.interfaceCount).map { d.getInterface(it) }
            .firstOrNull { it.interfaceClass == UsbConstants.USB_CLASS_COMM } else null
        for (i in listOfNotNull(control, data)) {
            if (!conn.claimInterface(i, true)) {
                claimed.forEach { conn.releaseInterface(it) }
                conn.close()
                throw IllegalStateException("Could not claim the USB interface (is another app using it?).")
            }
            claimed += i
        }
        val eps = (0 until data.endpointCount).map { data.getEndpoint(it) }
        val epIn = eps.first { it.type == UsbConstants.USB_ENDPOINT_XFER_BULK && it.direction == UsbConstants.USB_DIR_IN }
        val epOut = eps.first { it.type == UsbConstants.USB_ENDPOINT_XFER_BULK && it.direction == UsbConstants.USB_DIR_OUT }
        val port = SerialConnection(chip, AndroidUsbTransport(conn, epIn, epOut), (control ?: data).id)
        try {
            port.configure(baud)
        } catch (e: Exception) {
            port.markClosed()
            claimed.forEach { conn.releaseInterface(it) }
            conn.close()
            throw e
        }
        open[d.deviceName] = Open(conn, claimed, port)
        return "Opened ${d.deviceName} (${chip.label}) at $baud baud."
    }

    private fun port(id: String): SerialConnection {
        val name = runCatching { device(id).deviceName }.getOrDefault(id)
        return open[name]?.port ?: throw IllegalStateException("Port '$id' is not open. Use serial_open first.")
    }

    override fun write(id: String, data: ByteArray): Int = port(id).write(data)
    override fun read(id: String, totalMs: Long): ByteArray = port(id).read(totalMs)
    override fun isOpen(id: String): Boolean = runCatching { device(id).deviceName in open }.getOrDefault(false)

    @Synchronized
    override fun close(id: String) {
        val name = runCatching { device(id).deviceName }.getOrDefault(id)
        open.remove(name)?.let { o ->
            // Stop in-flight transfers before releasing the interface, so a read
            // thread cannot touch a freed connection.
            o.port.markClosed()
            o.ifaces.forEach { runCatching { o.conn.releaseInterface(it) } }
            runCatching { o.conn.close() }
        }
    }

    @Synchronized
    override fun closeAll() { open.keys.toList().forEach { close(it) } }

    companion object {
        const val ACTION_PERMISSION = "org.kairos.agent.USB_PERMISSION"
    }
}
