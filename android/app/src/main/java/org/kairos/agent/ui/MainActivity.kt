// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Main UI (desktop: kairos/gui/main_window.py).
package org.kairos.agent.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import org.kairos.agent.KairosApp
import org.kairos.agent.data.SecureStore
import org.kairos.agent.llm.Providers

// Desktop theme: dark with fluorescent-green text.
private val KairosGreen = Color(0xFF39FF14)
private val KairosColors = darkColorScheme(
    primary = KairosGreen, onPrimary = Color.Black, background = Color(0xFF101010),
    surface = Color(0xFF181818), onBackground = KairosGreen, onSurface = KairosGreen,
)

data class UiMsg(val role: String, val text: String)

class MainViewModel(app: android.app.Application) : AndroidViewModel(app) {
    private val k = app as KairosApp
    val messages = mutableStateListOf<UiMsg>().apply {
        addAll(k.store.recentMessages(100).map { UiMsg(it.role, it.content) })
    }
    private val main = android.os.Handler(android.os.Looper.getMainLooper())
    var busy by mutableStateOf(false); private set
    var status by mutableStateOf(""); private set

    fun send(text: String) {
        if (text.isBlank() || busy) return
        messages.add(UiMsg("user", text))
        val idx = messages.size
        messages.add(UiMsg("assistant", ""))
        busy = true; status = ""
        viewModelScope.launch {
            try {
                val reply = k.engine.chat(text) { d ->
                    // Deltas arrive on the IO thread; apply them on the main thread in order.
                    main.post { messages[idx] = messages[idx].copy(text = messages[idx].text + d) }
                }
                messages[idx] = UiMsg("assistant", reply)
            } catch (e: Exception) {
                messages[idx] = UiMsg("error", e.message ?: e.toString())
            } finally { busy = false }
        }
    }

    fun clear() { k.store.clearMessages(); messages.clear() }

    fun refreshModels(pid: String, onDone: (List<String>) -> Unit) = viewModelScope.launch {
        status = "Fetching models…"
        status = try {
            val models = k.llm.listModels(k.settings.apiUrl(pid), k.secrets.get(SecureStore.apiKeyName(pid)).orEmpty())
            k.settings.setCachedModels(pid, models); onDone(models); "${models.size} models"
        } catch (e: Exception) { "Model list failed: ${e.message}" }
    }
}

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colorScheme = KairosColors) { KairosRoot(vm, application as KairosApp) } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KairosRoot(vm: MainViewModel, app: KairosApp) {
    var tab by remember { mutableIntStateOf(0) }
    val tabs = listOf("Chat", "Provider", "Characters", "Memory")
    Scaffold(
        topBar = { TopAppBar(title = { Text("KAIROS") }) },
        bottomBar = {
            NavigationBar {
                tabs.forEachIndexed { i, t ->
                    NavigationBarItem(selected = tab == i, onClick = { tab = i },
                        icon = { Text(t.take(1)) }, label = { Text(t) }, modifier = Modifier.testTag("tab_$t"))
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            when (tab) {
                0 -> ChatScreen(vm)
                1 -> ProviderScreen(vm, app)
                2 -> CharacterScreen(app)
                else -> MemoryScreen(app)
            }
        }
    }
}

@Composable
fun ChatScreen(vm: MainViewModel) {
    var input by remember { mutableStateOf("") }
    val list = rememberLazyListState()
    LaunchedEffect(vm.messages.size) { if (vm.messages.isNotEmpty()) list.animateScrollToItem(vm.messages.size - 1) }
    Column(Modifier.fillMaxSize().padding(8.dp)) {
        LazyColumn(Modifier.weight(1f).testTag("messages"), state = list) {
            items(vm.messages) { m ->
                val mine = m.role == "user"
                Row(Modifier.fillMaxWidth().padding(4.dp),
                    horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
                    Surface(shape = RoundedCornerShape(12.dp),
                        color = when (m.role) { "user" -> Color(0xFF263826); "error" -> Color(0xFF402020); else -> Color(0xFF202020) }) {
                        Text(m.text.ifEmpty { "…" }, Modifier.padding(10.dp))
                    }
                }
            }
        }
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            OutlinedTextField(input, { input = it }, Modifier.weight(1f).testTag("input"),
                placeholder = { Text("Message Kairos (/remember, /recall, /whoami)") })
            Spacer(Modifier.width(6.dp))
            Button(onClick = { vm.send(input); input = "" }, enabled = !vm.busy, modifier = Modifier.testTag("send")) {
                Text(if (vm.busy) "…" else "Send")
            }
        }
        if (vm.status.isNotEmpty()) Text(vm.status)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderScreen(vm: MainViewModel, app: KairosApp) {
    val s = app.settings
    var pid by remember { mutableStateOf(s.activeProvider) }
    var url by remember(pid) { mutableStateOf(s.apiUrl(pid)) }
    var key by remember(pid) { mutableStateOf(app.secrets.get(SecureStore.apiKeyName(pid)).orEmpty()) }
    var model by remember(pid) { mutableStateOf(s.model(pid)) }
    var models by remember(pid) { mutableStateOf(s.cachedModels(pid)) }
    var expanded by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("LLM provider")
        Providers.PRESETS.forEach { p ->
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                RadioButton(selected = pid == p.id, onClick = { pid = p.id })
                Text(p.name)
            }
        }
        OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), label = { Text("API URL") })
        OutlinedTextField(key, { key = it }, Modifier.fillMaxWidth().testTag("api_key"), label = { Text("API key") },
            visualTransformation = PasswordVisualTransformation())
        ExposedDropdownMenuBox(expanded, { expanded = it }) {
            OutlinedTextField(model, { model = it }, Modifier.menuAnchor().fillMaxWidth(), label = { Text("Model") })
            ExposedDropdownMenu(expanded, { expanded = false }) {
                models.forEach { m -> DropdownMenuItem(text = { Text(m) }, onClick = { model = m; expanded = false }) }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                s.setApiUrl(pid, url); s.setModel(pid, model); app.secrets.put(SecureStore.apiKeyName(pid), key)
                s.activeProvider = pid; saved = "Saved. Active provider: $pid"
            }, modifier = Modifier.testTag("save_provider")) { Text("Save & activate") }
            OutlinedButton(onClick = {
                s.setApiUrl(pid, url); app.secrets.put(SecureStore.apiKeyName(pid), key)
                vm.refreshModels(pid) { models = it }
            }) { Text("Refresh models") }
        }
        if (saved.isNotEmpty()) Text(saved)
        if (vm.status.isNotEmpty()) Text(vm.status)
        Text("API keys are encrypted with the Android Keystore and never leave the device except to the provider.")
    }
}

@Composable
fun CharacterScreen(app: KairosApp) {
    var active by remember { mutableStateOf(app.characters.activeId) }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp)) {
        items(app.characters.all) { c ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp),
                onClick = { app.characters.activeId = c.id; app.settings.activeCharacter = c.id; active = c.id }) {
                Column(Modifier.padding(10.dp)) {
                    Text((if (active == c.id) "● " else "") + c.name, style = MaterialTheme.typography.titleMedium)
                    Text(c.description)
                    val caps = c.capabilities ?: app.characters.allCapabilities
                    Text("Tools: " + caps.joinToString { app.characters.labels[it] ?: it },
                        style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
fun MemoryScreen(app: KairosApp) {
    var items by remember { mutableStateOf(app.store.allMemories()) }
    var text by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().padding(12.dp)) {
        Row {
            OutlinedTextField(text, { text = it }, Modifier.weight(1f), label = { Text("Remember…") })
            Button(onClick = { app.store.remember(text); text = ""; items = app.store.allMemories() }) { Text("Add") }
        }
        LazyColumn {
            items(items) { m ->
                Row(Modifier.fillMaxWidth().padding(4.dp)) {
                    Text(m.content, Modifier.weight(1f))
                    TextButton(onClick = { app.store.forget(m.id); items = app.store.allMemories() }) { Text("Forget") }
                }
            }
        }
    }
}
