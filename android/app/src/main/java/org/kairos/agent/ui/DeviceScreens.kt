// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Browser (shared agent WebView) and USB serial screens.
package org.kairos.agent.ui

import android.view.ViewGroup
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.kairos.agent.KairosApp
import org.kairos.agent.serial.PortInfo
import org.kairos.agent.serial.SerialText

/** The agent's browser, shown live. The user can browse and solve CAPTCHAs here. */
@Composable
fun BrowserScreen(app: KairosApp) {
    val scope = rememberCoroutineScope()
    val current by app.browserPage.urlFlow.collectAsState()
    var address by remember(current) { mutableStateOf(if (current == "about:blank") "" else current) }
    var note by remember { mutableStateOf("") }
    val canUseAgent = app.characters.can("browser_control")
    Column(Modifier.fillMaxSize().testTag("browser")) {
        Row(Modifier.fillMaxWidth().padding(6.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            OutlinedTextField(address, { address = it }, Modifier.weight(1f).testTag("browser_url"), singleLine = true,
                label = { Text("Address") })
            Spacer(Modifier.width(4.dp))
            Button(onClick = {
                scope.launch { note = runCatching { app.browserAgent.goto(address); "" }.getOrElse { "Error: ${it.message}" } }
            }, modifier = Modifier.testTag("browser_go")) { Text("Go") }
        }
        Row(Modifier.padding(horizontal = 6.dp)) {
            TextButton(onClick = { scope.launch { app.browserPage.back() } }) { Text("\u25C0 Back") }
            TextButton(onClick = { scope.launch { app.browserPage.forward() } }) { Text("Forward \u25B6") }
            TextButton(onClick = { scope.launch { app.browserPage.reload() } }) { Text("Reload") }
            TextButton(onClick = { scope.launch { note = app.browserAgent.captcha() } }) { Text("CAPTCHA?") }
        }
        if (!canUseAgent)
            Text("The active character can't use browser automation; you can still browse here.", Modifier.padding(6.dp))
        if (note.isNotEmpty()) Text(note, Modifier.padding(6.dp).testTag("browser_note"))
        AndroidView(factory = { _ ->
            app.browserPage.view().also { v -> (v.parent as? ViewGroup)?.removeView(v)
                v.layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT) }
        }, modifier = Modifier.fillMaxSize().testTag("browser_view"), onRelease = { v -> (v.parent as? ViewGroup)?.removeView(v) })
    }
}

/** USB OTG serial terminal (CDC-ACM, CP210x, CH34x, FTDI). */
@Composable
fun SerialScreen(app: KairosApp) {
    val scope = rememberCoroutineScope()
    var ports by remember { mutableStateOf<List<PortInfo>>(emptyList()) }
    var selected by remember { mutableStateOf<String?>(null) }
    var baud by remember { mutableStateOf("115200") }
    var line by remember { mutableStateOf("") }
    var newline by remember { mutableStateOf(true) }
    var log by remember { mutableStateOf("") }
    // The open port is tracked by id, so changing the selection never leaves a stale port open.
    var connectedId by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("") }
    var allowWrite by remember { mutableStateOf(app.settings.serialWriteAllowed) }
    val allowed = app.characters.can("peripherals")
    val connected = connectedId != null && connectedId == selected

    fun refresh() {
        ports = runCatching { app.serialPorts.list() }.getOrDefault(emptyList())
        if (selected !in ports.map { it.id }) selected = ports.firstOrNull()?.id
    }
    LaunchedEffect(Unit) { refresh() }
    // Live read from the connected port only, paused while an agent job uses it.
    LaunchedEffect(connectedId) {
        val id = connectedId ?: return@LaunchedEffect
        while (isActive) {
            if (app.jobs.isBusy()) { delay(120); continue }
            val b = withContext(Dispatchers.IO) { runCatching { app.serialPorts.read(id, 250) }.getOrDefault(ByteArray(0)) }
            if (b.isNotEmpty()) log = (log + SerialText.show(b)).takeLast(20_000)
            delay(60)
        }
    }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("serial")) {
        item {
            Text("USB serial (OTG)", style = MaterialTheme.typography.titleMedium)
            Text("Plug an ESP32, Arduino or Pico into the phone with a USB OTG adapter. Supported chips: CDC-ACM, CP210x, CH34x, FTDI.")
            if (!allowed) Text("The active character is not permitted to use serial peripherals.")
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Switch(checked = allowWrite, onCheckedChange = { allowWrite = it; app.settings.serialWriteAllowed = it },
                    modifier = Modifier.testTag("serial_allow_write"))
                Spacer(Modifier.width(8.dp))
                Text("Allow agent serial writes")
            }
            Text("Off by default: an agent (or a web page) must not silently drive a connected board.",
                style = MaterialTheme.typography.bodySmall)
            Row { OutlinedButton(onClick = { refresh() }, modifier = Modifier.testTag("serial_refresh")) { Text("Refresh") } }
            if (ports.isEmpty()) Text("No USB serial devices found.", Modifier.testTag("serial_none"))
        }
        items(ports, key = { it.id }) { p ->
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                RadioButton(selected = selected == p.id, onClick = { selected = p.id })
                Text("${p.description} \u00B7 ${p.chip?.label}" + if (p.permitted) "" else " \u00B7 needs permission")
            }
        }
        item {
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                OutlinedTextField(baud, { baud = it.filter(Char::isDigit) }, Modifier.width(140.dp), label = { Text("Baud") }, singleLine = true)
                Spacer(Modifier.width(8.dp))
                Button(enabled = allowed && selected != null, onClick = click@{
                    val id = selected ?: return@click
                    if (connected) {
                        scope.launch { withContext(Dispatchers.IO) { runCatching { app.serialPorts.close(id) } }; connectedId = null; status = "Disconnected." }
                        return@click
                    }
                    scope.launch {
                        val r = withContext(Dispatchers.IO) { runCatching { app.serialPorts.open(id, baud.toIntOrNull() ?: 115200) }.getOrElse { "Error: ${it.message}" } }
                        status = r
                        if (r.startsWith("Opened") || r.startsWith("Port")) connectedId = id
                        refresh()
                    }
                }, modifier = Modifier.testTag("serial_connect")) { Text(if (connected) "Disconnect" else "Connect") }
            }
            if (status.isNotEmpty()) Text(status, Modifier.testTag("serial_status"))
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                OutlinedTextField(line, { line = it }, Modifier.weight(1f), label = { Text("Send (\\n, \\xNN escapes)") }, singleLine = true)
                Spacer(Modifier.width(6.dp))
                Checkbox(checked = newline, onCheckedChange = { newline = it })
                Text("\\n")
                Button(enabled = connected, onClick = click@{
                    val id = selected ?: return@click
                    val data = SerialText.unescape(if (newline) line + "\\n" else line); line = ""
                    scope.launch { withContext(Dispatchers.IO) { runCatching { app.serialPorts.write(id, data) } } }
                }) { Text("Send") }
            }
            Row {
                OutlinedButton(onClick = { log = "" }) { Text("Clear log") }
            }
            SelectionContainer { Text(log.ifEmpty { "(no data yet)" }, Modifier.padding(top = 8.dp).testTag("serial_log"),
                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace) }
        }
    }
}
