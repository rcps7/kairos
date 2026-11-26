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

    private var _mode by mutableStateOf(k.settings.agentMode)
    var mode: String
        get() = _mode
        set(v) { _mode = v; k.settings.agentMode = v }

    /** Every turn goes through the FIFO job queue, so the user can keep typing while one runs. */
    fun send(text: String) {
        if (text.isBlank()) return
        messages.add(UiMsg("user", if (mode == "chat") text else "[$mode] $text"))
        val idx = messages.size
        messages.add(UiMsg("assistant", ""))
        val m = mode
        busy = true
        k.jobs.submit(org.kairos.agent.jobs.Job(label = "chat",
            onProgress = { _, p -> main.post { status = p } },
            onDone = { _, r -> main.post {
                messages[idx] = UiMsg("assistant", r as String); finish()
                if (k.settings.speakReplies) k.speaker.speak(r)
            } },
            onError = { _, e -> main.post { messages[idx] = UiMsg("error", e.message ?: e.toString()); finish() } },
        ) { _, progress ->
            k.agent.run(text, m, progress) { d ->
                // Deltas arrive on a worker thread; apply them on the main thread in order.
                main.post { messages[idx] = messages[idx].copy(text = messages[idx].text + d) }
            }.text
        })
    }

    private fun finish() = Unit

    init {
        viewModelScope.launch { k.jobs.pendingFlow.collect { n -> busy = n > 0; if (n == 0) status = "" } }
    }

    fun clear() { k.store.clearMessages(); messages.clear() }

    var speak by mutableStateOf(k.settings.speakReplies); private set
    fun toggleSpeak() { speak = !speak; k.settings.speakReplies = speak; if (!speak) k.speaker.stop() }

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
    val tabs = listOf("Chat", "Provider", "Characters", "Memory", "Library", "Plans")
    Scaffold(
        topBar = {
            var more by remember { mutableStateOf(false) }
            TopAppBar(title = { Text("KAIROS") }, actions = {
                TextButton(onClick = { more = true }, modifier = Modifier.testTag("more")) { Text("More ▾") }
                DropdownMenu(expanded = more, onDismissRequest = { more = false }) {
                    listOf(10 to "PC", 11 to "Browser", 12 to "Serial", 7 to "Skills", 6 to "Connect", 8 to "Git", 9 to "Media").forEach { (i, t) ->
                        DropdownMenuItem(text = { Text(when (t) { "Connect" -> "Email & Telegram"; "Media" -> "Media & Voice"; "PC" -> "PC remote"; "Serial" -> "USB serial"; else -> t }) },
                            onClick = { tab = i; more = false }, modifier = Modifier.testTag("tab_$t"))
                    }
                }
            })
        },
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
                3 -> MemoryScreen(app)
                4 -> LibraryScreen(app)
                5 -> PlansScreen(app)
                6 -> ConnectScreen(app)
                7 -> SkillsScreen(app)
                8 -> GitScreen(app)
                9 -> MediaScreen(app)
                10 -> PcScreen(app)
                11 -> BrowserScreen(app)
                else -> SerialScreen(app)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(vm: MainViewModel) {
    var input by remember { mutableStateOf("") }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var listening by remember { mutableStateOf(false) }
    var level by remember { mutableFloatStateOf(0f) }
    var voiceMsg by remember { mutableStateOf("") }
    val app = ctx.applicationContext as KairosApp
    val system = remember {
        org.kairos.agent.voice.Listener(ctx,
            onLevel = { level = it },
            onPartial = { input = it },
            onResult = { input = it; listening = false; voiceMsg = "" },
            onError = { voiceMsg = it; listening = false })
    }
    var vosk by remember { mutableStateOf<org.kairos.agent.voice.VoskListener?>(null) }
    // Pick the recognizer: the system one, or offline Vosk when chosen or when there is no system service.
    val listener = remember {
        object {
            fun start() {
                val model = org.kairos.agent.voice.VoskModels.installed(java.io.File(app.filesDir, "vosk"))
                val engine = app.settings.voiceEngine
                val useVosk = model != null && (engine == "vosk" || (engine == "auto" && !system.available()))
                if (useVosk) {
                    (vosk ?: org.kairos.agent.voice.VoskListener(model!!,
                        level = { level = it }, partial = { input = it },
                        result = { input = it; listening = false; voiceMsg = "" },
                        fail = { voiceMsg = it; listening = false }).also { vosk = it }).start()
                } else if (engine == "vosk") { voiceMsg = "Download an offline speech model in Media & Voice first."; listening = false }
                else system.start()
            }
            fun stop() { system.stop(); vosk?.stop() }
        }
    }
    DisposableEffect(Unit) { onDispose { listener.stop() } }
    val micPermission = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) { listening = true; voiceMsg = "Listening…"; listener.start() } else voiceMsg = "Microphone permission is needed for Talk."
    }
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
                placeholder = { Text("Message Kairos (/help for commands)") })
            Spacer(Modifier.width(4.dp))
            OutlinedButton(onClick = {
                if (listening) { listener.stop(); listening = false; voiceMsg = "" }
                else micPermission.launch(android.Manifest.permission.RECORD_AUDIO)
            }, contentPadding = PaddingValues(horizontal = 10.dp), modifier = Modifier.testTag("talk")) { Text(if (listening) "Stop" else "Talk") }
            Spacer(Modifier.width(4.dp))
            Button(onClick = { vm.send(input); input = "" }, modifier = Modifier.testTag("send")) {
                Text("Send")
            }
        }
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            listOf("chat" to "Chat", "plan" to "Plan", "execute" to "Execute").forEach { (id, label) ->
                FilterChip(selected = vm.mode == id, onClick = { vm.mode = id }, label = { Text(label) },
                    modifier = Modifier.padding(end = 6.dp).testTag("mode_$id"))
            }
            FilterChip(selected = vm.speak, onClick = { vm.toggleSpeak() }, label = { Text("Speak") },
                modifier = Modifier.padding(end = 6.dp).testTag("speak"))
            if (vm.busy) Text("working…", Modifier.testTag("busy"))
        }
        if (listening) LinearProgressIndicator(progress = { level }, modifier = Modifier.fillMaxWidth().testTag("voice_meter"))
        if (voiceMsg.isNotEmpty()) Text(voiceMsg, Modifier.testTag("voice_msg"))
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
            Card(onClick = { app.characters.activeId = c.id; app.settings.activeCharacter = c.id; active = c.id },
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
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


/** Knowledge library (desktop: Library tab + "Learn from page"). */
@Composable
fun LibraryScreen(app: KairosApp) {
    var docs by remember { mutableStateOf(app.store.allDocuments()) }
    var url by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(12.dp)) {
        Row {
            OutlinedTextField(url, { url = it }, Modifier.weight(1f).testTag("learn_url"), label = { Text("Learn from URL") }, singleLine = true)
            Button(enabled = !busy && url.isNotBlank(), onClick = {
                busy = true; status = "Learning…"
                scope.launch {
                    status = try { val r = app.webTools.learn(url.trim()); url = ""; "Saved: ${r.title}" }
                    catch (e: Exception) { "Failed: ${e.message}" }
                    docs = app.store.allDocuments(); busy = false
                }
            }) { Text("Learn") }
        }
        OutlinedTextField(query, { query = it; docs = if (it.isBlank()) app.store.allDocuments() else app.store.searchDocuments(it, 50) },
            Modifier.fillMaxWidth(), label = { Text("Search library") }, singleLine = true)
        if (status.isNotEmpty()) Text(status)
        LazyColumn {
            items(docs) { d ->
                Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                    Column(Modifier.padding(10.dp)) {
                        Text(d.title.ifBlank { d.url }, style = MaterialTheme.typography.titleSmall)
                        Text(d.url, style = MaterialTheme.typography.bodySmall)
                        Text(d.summary.take(600))
                        TextButton(onClick = { app.store.deleteDocument(d.id); docs = app.store.allDocuments() }) { Text("Delete") }
                    }
                }
            }
        }
    }
}


/** Durable plans (desktop: Plans panel). */
@Composable
fun PlansScreen(app: KairosApp) {
    var plans by remember { mutableStateOf(app.store.list(100)) }
    LaunchedEffect(Unit) { while (true) { kotlinx.coroutines.delay(1500); plans = app.store.list(100) } }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("plans")) {
        if (plans.isEmpty()) item { Text("No plans yet. Switch the chat to Plan or Execute mode and describe a goal.") }
        items(plans) { p ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(10.dp)) {
                    Text("${p.goal} [${p.status}]", style = MaterialTheme.typography.titleSmall)
                    p.steps.forEach { s -> Text("${s.idx + 1}. [${s.status}] ${s.title}") }
                    TextButton(onClick = { app.store.delete(p.id); plans = app.store.list(100) }) { Text("Delete") }
                }
            }
        }
    }
}


/** Email and Telegram setup plus an inbox (desktop: Edit -> Email / Telegram Settings, Mail panel). */
@Composable
fun ConnectScreen(app: KairosApp) {
    val s = app.settings
    val scope = rememberCoroutineScope()
    var addr by remember { mutableStateOf(s.emailAddress) }
    var pass by remember { mutableStateOf(app.secrets.get(SecureStore.EMAIL_PASSWORD).orEmpty()) }
    var imap by remember { mutableStateOf(s.imapHost) }
    var imapPort by remember { mutableStateOf(s.imapPort.toString()) }
    var smtp by remember { mutableStateOf(s.smtpHost) }
    var smtpPort by remember { mutableStateOf(s.smtpPort.toString()) }
    var mailStatus by remember { mutableStateOf("") }
    var inbox by remember { mutableStateOf<List<org.kairos.agent.email.MailItem>>(emptyList()) }
    var to by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }

    var token by remember { mutableStateOf(app.secrets.get(SecureStore.TELEGRAM_TOKEN).orEmpty()) }
    var allowed by remember { mutableStateOf(s.telegramAllowed) }
    var tgOn by remember { mutableStateOf(s.telegramEnabled) }
    var tgStatus by remember { mutableStateOf(org.kairos.agent.telegram.TelegramService.status) }
    LaunchedEffect(Unit) { while (true) { kotlinx.coroutines.delay(1000); tgStatus = org.kairos.agent.telegram.TelegramService.status } }

    fun saveEmail() {
        s.emailAddress = addr; s.imapHost = imap; s.smtpHost = smtp
        s.imapPort = imapPort.toIntOrNull() ?: 993; s.smtpPort = smtpPort.toIntOrNull() ?: 465
        app.secrets.put(SecureStore.EMAIL_PASSWORD, pass.ifEmpty { null })
    }

    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("connect")) {
        item {
            Text("Email (IMAP/SMTP over SSL)", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(addr, { addr = it }, Modifier.fillMaxWidth(), label = { Text("Email address") }, singleLine = true)
            OutlinedTextField(pass, { pass = it }, Modifier.fillMaxWidth(), label = { Text("Password / app password") },
                singleLine = true, visualTransformation = PasswordVisualTransformation())
            Row {
                OutlinedTextField(imap, { imap = it }, Modifier.weight(2f), label = { Text("IMAP host") }, singleLine = true)
                OutlinedTextField(imapPort, { imapPort = it }, Modifier.weight(1f), label = { Text("Port") }, singleLine = true)
            }
            Row {
                OutlinedTextField(smtp, { smtp = it }, Modifier.weight(2f), label = { Text("SMTP host") }, singleLine = true)
                OutlinedTextField(smtpPort, { smtpPort = it }, Modifier.weight(1f), label = { Text("Port") }, singleLine = true)
            }
            Row {
                Button(onClick = { saveEmail(); mailStatus = "Saved." }, Modifier.testTag("email_save")) { Text("Save") }
                Spacer(Modifier.width(8.dp))
                Button(onClick = {
                    saveEmail(); mailStatus = "Reading inbox…"
                    scope.launch {
                        mailStatus = try { inbox = app.email.readMail(10); "${inbox.size} message(s)." } catch (e: Exception) { "Email error: ${e.message}" }
                    }
                }) { Text("Read inbox") }
            }
            if (mailStatus.isNotEmpty()) Text(mailStatus, Modifier.testTag("mail_status"))
        }
        items(inbox) { m ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(10.dp)) {
                    Text(m.subject.ifBlank { "(no subject)" }, style = MaterialTheme.typography.titleSmall)
                    Text("${m.from} · ${m.date}", style = MaterialTheme.typography.bodySmall)
                    Text(m.body.trim().take(400))
                }
            }
        }
        item {
            Text("Compose", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
            OutlinedTextField(to, { to = it }, Modifier.fillMaxWidth(), label = { Text("To") }, singleLine = true)
            OutlinedTextField(subject, { subject = it }, Modifier.fillMaxWidth(), label = { Text("Subject") }, singleLine = true)
            OutlinedTextField(body, { body = it }, Modifier.fillMaxWidth().heightIn(min = 100.dp), label = { Text("Message") })
            Button(enabled = to.isNotBlank(), onClick = {
                saveEmail(); mailStatus = "Sending…"
                scope.launch {
                    mailStatus = try { app.email.sendMail(to.trim(), subject, body); body = ""; "Email sent." } catch (e: Exception) { "Send error: ${e.message}" }
                }
            }) { Text("Send email") }
        }
        item {
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            Text("Telegram bot", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(token, { token = it }, Modifier.fillMaxWidth().testTag("tg_token"), label = { Text("Bot token from @BotFather") },
                singleLine = true, visualTransformation = PasswordVisualTransformation())
            OutlinedTextField(allowed, { allowed = it }, Modifier.fillMaxWidth(), label = { Text("Allowed user IDs (comma-separated)") }, singleLine = true)
            Text("Only these Telegram users can command KAIROS. Send /whoami to your bot to see your ID. An empty list blocks everyone.",
                style = MaterialTheme.typography.bodySmall)
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Switch(checked = tgOn, onCheckedChange = { on ->
                    app.secrets.put(SecureStore.TELEGRAM_TOKEN, token.trim().ifEmpty { null })
                    s.telegramAllowed = allowed
                    tgOn = on; s.telegramEnabled = on
                    if (on) org.kairos.agent.telegram.TelegramService.start(app) else org.kairos.agent.telegram.TelegramService.stop(app)
                }, modifier = Modifier.testTag("tg_switch"))
                Spacer(Modifier.width(8.dp))
                Text(if (tgOn) "Bot on" else "Bot off")
            }
            Text("Status: $tgStatus", Modifier.testTag("tg_status"))
            if (token.isNotBlank() && !org.kairos.agent.telegram.validateTokenFormat(token))
                Text("Token format looks wrong (expected '<digits>:<secret>').", color = Color(0xFFFF6060))
        }
        item {
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            Text("Kill switch", style = MaterialTheme.typography.titleMedium)
            var confirm by remember { mutableStateOf(false) }
            if (!confirm) OutlinedButton(onClick = { confirm = true }) { Text("Shut down KAIROS…") }
            else Row {
                Button(onClick = { app.emergencyKill() }, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB00020))) { Text("YES - SHUT DOWN") }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { confirm = false }) { Text("Cancel") }
            }
        }
    }
}


/** Skills: list, create (template or LLM-generated), edit, run and delete (desktop Skills panel). */
@Composable
fun SkillsScreen(app: KairosApp) {
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf(app.skills.listSkills()) }
    var name by remember { mutableStateOf("") }
    var desc by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var args by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    fun refresh() { list = app.skills.listSkills() }
    fun parseArgs() = args.split(Regex("\\s+")).filter { '=' in it }.associate { it.substringBefore('=') to it.substringAfter('=') }

    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("skills")) {
        item {
            Text("Skills run as JavaScript in a sandbox with no file, network or Java access; they reach KAIROS only through the `kairos` object.",
                style = MaterialTheme.typography.bodySmall)
        }
        items(list) { sk ->
            Card(onClick = { name = sk.name; desc = sk.description; code = app.skills.readSource(sk.name); status = "Loaded ${sk.name}." },
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).testTag("skill_${sk.name}")) {
                Column(Modifier.padding(10.dp)) {
                    Text(sk.name, style = MaterialTheme.typography.titleSmall)
                    if (sk.description.isNotBlank()) Text(sk.description, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item {
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            OutlinedTextField(name, { name = it.lowercase() }, Modifier.fillMaxWidth().testTag("skill_name"), label = { Text("Name (a-z, 0-9, _)") }, singleLine = true)
            OutlinedTextField(desc, { desc = it }, Modifier.fillMaxWidth(), label = { Text("Description") })
            Row {
                OutlinedButton(onClick = { code = org.kairos.agent.skills.SkillManager.template(name, desc) }) { Text("Template") }
                Spacer(Modifier.width(8.dp))
                OutlinedButton(enabled = name.isNotBlank() && desc.isNotBlank(), onClick = {
                    if (!app.characters.can("skills_manage")) { status = "Not permitted: skills manage."; return@OutlinedButton }
                    status = "Generating…"
                    scope.launch { code = app.generateSkill(name, desc); status = "Review the code, then Save." }
                }) { Text("Generate with AI") }
            }
            OutlinedTextField(code, { code = it }, Modifier.fillMaxWidth().heightIn(min = 160.dp).testTag("skill_code"),
                label = { Text("Code") }, textStyle = LocalTextStyle.current.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace))
            Row {
                Button(enabled = name.isNotBlank() && code.isNotBlank(), onClick = {
                    status = if (!app.characters.can("skills_manage")) "Not permitted: skills manage." else
                        try { app.skills.saveSource(name, code); refresh(); "Saved $name." } catch (e: Exception) { "Save failed: ${e.message}" }
                }, modifier = Modifier.testTag("skill_save")) { Text("Save") }
                Spacer(Modifier.width(8.dp))
                OutlinedButton(enabled = name.isNotBlank(), onClick = {
                    status = if (!app.characters.can("skills_manage")) "Not permitted: skills manage." else
                        try { if (app.skills.deleteSkill(name)) { refresh(); code = ""; "Deleted $name." } else "Not found." } catch (e: Exception) { "Delete failed: ${e.message}" }
                }) { Text("Delete") }
            }
            OutlinedTextField(args, { args = it }, Modifier.fillMaxWidth(), label = { Text("Arguments: key=value key2=value2") }, singleLine = true)
            Button(enabled = name.isNotBlank(), onClick = {
                when {
                    !app.characters.can("skills_run") -> status = "Not permitted: skills run."
                    !app.characters.allowsSkill(name) -> status = "This character may not run '$name'."
                    else -> { status = "Running…"; output = ""
                        scope.launch {
                            try { output = app.queued("skill") { app.skills.runSkill(name, parseArgs()) }; status = "Done." }
                            catch (e: Exception) { status = "Skill error: ${e.message}" }
                        } }
                }
            }, modifier = Modifier.testTag("skill_run")) { Text("Run") }
            if (status.isNotEmpty()) Text(status, Modifier.testTag("skill_status"))
            if (output.isNotEmpty()) SelectionContainerText(output)
        }
    }
}

@Composable
private fun SelectionContainerText(text: String) {
    androidx.compose.foundation.text.selection.SelectionContainer {
        Text(text, Modifier.padding(top = 8.dp).testTag("skill_output"))
    }
}


/** Git workflows with JGit (desktop: Git panel / git_tool.py). Repos live in the app's private storage. */
@Composable
fun GitScreen(app: KairosApp) {
    val s = app.settings
    val scope = rememberCoroutineScope()
    var enabled by remember { mutableStateOf(s.gitEnabled) }
    var allowPull by remember { mutableStateOf(s.gitAllowPull) }
    var allowPush by remember { mutableStateOf(s.gitAllowPush) }
    var authorName by remember { mutableStateOf(s.gitAuthorName) }
    var authorEmail by remember { mutableStateOf(s.gitAuthorEmail) }
    var token by remember { mutableStateOf(app.secrets.get(SecureStore.GIT_TOKEN).orEmpty()) }
    var repo by remember { mutableStateOf(s.gitActiveRepo) }
    var cloneUrl by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var branch by remember { mutableStateOf("") }
    var out by remember { mutableStateOf("") }
    val repos = remember(out) { app.git.root.listFiles { f -> java.io.File(f, ".git").isDirectory }?.map { it.name }?.sorted().orEmpty() }

    fun save() {
        s.gitEnabled = enabled; s.gitAllowPull = allowPull; s.gitAllowPush = allowPush
        s.gitAuthorName = authorName; s.gitAuthorEmail = authorEmail; s.gitActiveRepo = repo
        app.secrets.put(SecureStore.GIT_TOKEN, token.trim().ifEmpty { null })
    }
    fun op(label: String, block: () -> String) {
        save()
        if (!app.characters.can("git_ops")) { out = "'${app.characters.active().name}' is not permitted to use git."; return }
        out = "$label…"
        scope.launch { out = try { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { block() } } catch (e: Exception) { "Git error: ${e.message}" } }
    }
    @Composable fun Toggle(label: String, v: Boolean, tag: String, set: (Boolean) -> Unit) =
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Switch(checked = v, onCheckedChange = { set(it); save() }, modifier = Modifier.testTag(tag)); Spacer(Modifier.width(8.dp)); Text(label)
        }

    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("git")) {
        item {
            Toggle("Git enabled", enabled, "git_enabled") { enabled = it }
            Toggle("Allow pull / clone", allowPull, "git_pull_ok") { allowPull = it }
            Toggle("Allow push (never forced)", allowPush, "git_push_ok") { allowPush = it }
            Row {
                OutlinedTextField(authorName, { authorName = it }, Modifier.weight(1f), label = { Text("Author name") }, singleLine = true)
                OutlinedTextField(authorEmail, { authorEmail = it }, Modifier.weight(1f), label = { Text("Author email") }, singleLine = true)
            }
            OutlinedTextField(token, { token = it }, Modifier.fillMaxWidth(), label = { Text("HTTPS token (for private repos / push)") },
                singleLine = true, visualTransformation = PasswordVisualTransformation())
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            OutlinedTextField(repo, { repo = it.trim() }, Modifier.fillMaxWidth().testTag("git_repo"), label = { Text("Repository folder") }, singleLine = true)
            if (repos.isNotEmpty()) Row { repos.take(4).forEach { r -> AssistChip(onClick = { repo = r; save() }, label = { Text(r) }, modifier = Modifier.padding(end = 4.dp)) } }
            Row {
                OutlinedButton(enabled = repo.isNotBlank(), onClick = { op("Initializing") { app.git.init(repo) } }, modifier = Modifier.testTag("git_init")) { Text("Init") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { op("Status") { app.git.summary(repo) } }, modifier = Modifier.testTag("git_status")) { Text("Status") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { op("Log") { app.git.log(20, repo) } }, modifier = Modifier.testTag("git_log")) { Text("Log") }
            }
            Row {
                OutlinedButton(onClick = { op("Diff") { app.git.diff(false, null, repo) } }) { Text("Diff") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { op("Branches") { app.git.branches(repo) } }) { Text("Branches") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { op("Remotes") { app.git.remotes(repo) } }) { Text("Remotes") }
            }
            OutlinedTextField(cloneUrl, { cloneUrl = it }, Modifier.fillMaxWidth(), label = { Text("Clone https:// URL") }, singleLine = true)
            OutlinedButton(enabled = cloneUrl.isNotBlank() && repo.isNotBlank(), onClick = { op("Cloning") { app.git.clone(cloneUrl.trim(), repo) } }) { Text("Clone into folder") }
            OutlinedTextField(message, { message = it }, Modifier.fillMaxWidth().testTag("git_message"), label = { Text("Commit message") })
            Button(enabled = message.isNotBlank(), onClick = { op("Committing") { app.git.commit(message, addAll = true, repo = repo).also { message = "" } } },
                modifier = Modifier.testTag("git_commit")) { Text("Stage all & commit") }
            OutlinedTextField(branch, { branch = it }, Modifier.fillMaxWidth(), label = { Text("Branch") }, singleLine = true)
            Row {
                OutlinedButton(enabled = branch.isNotBlank(), onClick = { op("Creating branch") { app.git.createBranch(branch, true, repo) } }) { Text("New branch") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(enabled = branch.isNotBlank(), onClick = { op("Checking out") { app.git.checkout(branch, repo) } }) { Text("Checkout") }
            }
            Row {
                OutlinedButton(onClick = { op("Pulling") { app.git.pull(repo) } }) { Text("Pull (ff-only)") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { op("Pushing") { app.git.push("origin", null, repo) } }) { Text("Push") }
            }
            if (out.isNotEmpty()) androidx.compose.foundation.text.selection.SelectionContainer {
                Text(out, Modifier.padding(top = 8.dp).testTag("git_out"),
                    style = LocalTextStyle.current.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace))
            }
        }
    }
}


/** Media downloads (desktop MediaDownloader + media library) and voice settings, including the Vosk model. */
@Composable
fun MediaScreen(app: KairosApp) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf("") }
    var progress by remember { mutableFloatStateOf(-1f) }
    var line by remember { mutableStateOf("") }
    var procId by remember { mutableStateOf<String?>(null) }
    var library by remember { mutableStateOf(app.media.index.prune().sortedByDescending { it.createdAt }) }
    var engine by remember { mutableStateOf(app.settings.voiceEngine) }
    var modelUrl by remember { mutableStateOf(app.settings.voskModelUrl) }
    val voskDir = java.io.File(app.filesDir, "vosk")
    var voskReady by remember { mutableStateOf(org.kairos.agent.voice.VoskModels.installed(voskDir) != null) }
    var voskMsg by remember { mutableStateOf("") }
    val systemAvailable = remember { android.speech.SpeechRecognizer.isRecognitionAvailable(ctx) }

    fun start(fmt: String) {
        if (!app.characters.can("download_media")) { line = "'${app.characters.active().name}' is not permitted to download media."; return }
        val id = java.util.UUID.randomUUID().toString(); procId = id; progress = 0f; line = "Preparing yt-dlp (first run unpacks it)…"
        app.mediaScope.launch {
            val msg = try {
                val m = app.media.download(url, fmt, id) { p, l -> scope.launch { progress = p / 100f; line = l } }
                "Saved: ${m.title}"
            } catch (e: Exception) { "Download error: ${e.message}" }
            scope.launch { line = msg; progress = -1f; procId = null; library = app.media.index.list().sortedByDescending { it.createdAt } }
        }
    }
    fun open(item: org.kairos.agent.media.MediaItem, share: Boolean) = runCatching {
        val uri = androidx.core.content.FileProvider.getUriForFile(ctx, ctx.packageName + ".files", java.io.File(item.path))
        val mime = if (item.type == "audio") "audio/mpeg" else "video/mp4"
        val i = if (share) android.content.Intent(android.content.Intent.ACTION_SEND).setType(mime).putExtra(android.content.Intent.EXTRA_STREAM, uri)
                else android.content.Intent(android.content.Intent.ACTION_VIEW).setDataAndType(uri, mime)
        ctx.startActivity(android.content.Intent.createChooser(i.addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION), item.title)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    }.onFailure { line = "Can't open: ${it.message}" }

    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("media")) {
        item {
            Text("Download audio / video", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth().testTag("media_url"), label = { Text("Video page URL") }, singleLine = true)
            Row(Modifier.padding(vertical = 4.dp)) {
                Button(enabled = url.isNotBlank() && procId == null, onClick = { start("mp3") }, modifier = Modifier.testTag("media_mp3")) { Text("MP3 (audio)") }
                Spacer(Modifier.width(6.dp))
                Button(enabled = url.isNotBlank() && procId == null, onClick = { start("mp4") }, modifier = Modifier.testTag("media_mp4")) { Text("MP4 (video)") }
                Spacer(Modifier.width(6.dp))
                if (procId != null) OutlinedButton(onClick = { procId?.let { app.media.cancel(it) } }) { Text("Cancel") }
            }
            if (progress >= 0f) LinearProgressIndicator(progress = { progress.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
            if (line.isNotEmpty()) Text(line, Modifier.testTag("media_status"), maxLines = 3)
            OutlinedButton(onClick = {
                line = "Updating yt-dlp…"
                app.mediaScope.launch {
                    val r = runCatching { app.media.ensureInit(); org.kairos.agent.media.YtDlpEngine(app).update() }
                    scope.launch { line = r.fold({ "yt-dlp: $it (${app.media.version() ?: "?"})" }, { "Update failed: ${it.message}" }) }
                }
            }) { Text("Update yt-dlp") }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            Text("Library (${library.size})", style = MaterialTheme.typography.titleMedium)
        }
        items(library, key = { it.id }) { m ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(10.dp)) {
                    Text((if (m.type == "audio") "♪ " else "▶ ") + m.title)
                    Row {
                        TextButton(onClick = { open(m, false) }) { Text("Open") }
                        TextButton(onClick = { open(m, true) }) { Text("Share") }
                        TextButton(onClick = { app.media.index.remove(m.id); library = app.media.index.list().sortedByDescending { it.createdAt } }) { Text("Delete") }
                    }
                }
            }
        }
        item {
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            Text("Voice input", style = MaterialTheme.typography.titleMedium)
            Text(if (systemAvailable) "System speech recognition is available." else "No system speech recognition on this device — use offline (Vosk).")
            listOf("auto" to "Automatic", "system" to "System recognizer", "vosk" to "Offline (Vosk)").forEach { (id, label) ->
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    RadioButton(selected = engine == id, onClick = { engine = id; app.settings.voiceEngine = id }, modifier = Modifier.testTag("voice_$id"))
                    Text(label)
                }
            }
            OutlinedTextField(modelUrl, { modelUrl = it }, Modifier.fillMaxWidth(), label = { Text("Vosk model URL (zip)") }, singleLine = true)
            Text("Models for other languages: alphacephei.com/vosk/models")
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Button(onClick = {
                    app.settings.voskModelUrl = modelUrl; voskMsg = "Downloading model…"
                    app.mediaScope.launch {
                        val r = runCatching {
                            org.kairos.agent.voice.VoskModels.download(modelUrl, voskDir) { d, t ->
                                if (d % (1 shl 20) < 65536) scope.launch { voskMsg = if (t > 0) "Downloading model… ${d * 100 / t}%" else "Downloading… ${d shr 20} MB" }
                            }
                        }
                        scope.launch { voskReady = r.isSuccess; voskMsg = r.fold({ "Offline model installed." }, { "Model download failed: ${it.message}" }) }
                    }
                }) { Text(if (voskReady) "Re-download model" else "Download model") }
                Spacer(Modifier.width(6.dp))
                if (voskReady) OutlinedButton(onClick = { java.io.File(voskDir, "model").deleteRecursively(); voskReady = false; voskMsg = "Model removed." }) { Text("Remove") }
            }
            if (voskMsg.isNotEmpty()) Text(voskMsg)
        }
    }
}


/** Control a desktop Kairos over the LAN (desktop: kairos/remote_api.py). */
@Composable
fun PcScreen(app: KairosApp) {
    val scope = rememberCoroutineScope()
    var link by remember { mutableStateOf(app.secrets.get(SecureStore.REMOTE_PAIRING).orEmpty()) }
    val pairing = remember(link) { runCatching { org.kairos.agent.remote.PairingLink.parse(link) }.getOrNull() }
    var status by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf("chat") }
    var output by remember { mutableStateOf("") }
    var jobs by remember { mutableStateOf<List<org.kairos.agent.remote.RemoteJob>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var confirmKill by remember { mutableStateOf(false) }

    fun io(label: String, block: (org.kairos.agent.remote.RemoteClient) -> Unit) {
        val c = app.remote() ?: run { status = "Pair with a PC first."; return }
        busy = true; status = label
        app.mediaScope.launch {
            val err = runCatching { block(c) }.exceptionOrNull()
            scope.launch { busy = false; if (err != null) status = "Error: ${err.message}" }
        }
    }

    LazyColumn(Modifier.fillMaxSize().padding(12.dp).testTag("pc")) {
        item {
            Text("Remote control of Kairos on your PC", style = MaterialTheme.typography.titleMedium)
            Text("On the PC run: python -m kairos.remote_api pair, set remote.enabled, restart Kairos, then paste the kairos://pair link here. Both devices must be on the same network.")
            OutlinedTextField(link, { link = it.trim() }, Modifier.fillMaxWidth().testTag("pc_link"), label = { Text("Pairing link") },
                singleLine = true, visualTransformation = PasswordVisualTransformation())
            Row {
                Button(enabled = pairing != null, onClick = {
                    app.secrets.put(SecureStore.REMOTE_PAIRING, link); status = "Paired with ${pairing?.name}."
                }, modifier = Modifier.testTag("pc_save")) { Text("Save pairing") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { app.secrets.put(SecureStore.REMOTE_PAIRING, null); link = ""; status = "Unpaired." }) { Text("Forget") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(enabled = !busy, onClick = { io("Connecting…") { c -> val s = c.ping(); scope.launch { status = "Connected: $s" } } },
                    modifier = Modifier.testTag("pc_ping")) { Text("Test") }
            }
            if (link.isNotEmpty() && pairing == null) Text("That doesn't look like a valid pairing link.")
            if (status.isNotEmpty()) Text(status, Modifier.testTag("pc_status"))
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            OutlinedTextField(prompt, { prompt = it }, Modifier.fillMaxWidth().testTag("pc_prompt"), label = { Text("Ask or give the PC a task") })
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                listOf("chat" to "Chat", "plan" to "Plan", "execute" to "Execute").forEach { (id, l) ->
                    FilterChip(selected = mode == id, onClick = { mode = id }, label = { Text(l) }, modifier = Modifier.padding(end = 6.dp))
                }
            }
            Row {
                Button(enabled = !busy && prompt.isNotBlank(), onClick = {
                    val p = prompt
                    io("Running on PC…") { c ->
                        val j = c.runJob(p, mode) { u -> scope.launch { status = "PC job ${u.id}: ${u.status} ${u.progress}".trim() } }
                        val js = c.jobs()
                        scope.launch { output = j.result ?: "Error: ${j.error}"; status = "PC job ${j.id}: ${j.status}"; jobs = js }
                    }
                }, modifier = Modifier.testTag("pc_run")) { Text("Run on PC") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(enabled = !busy, onClick = { io("Loading jobs…") { c -> val js = c.jobs(); scope.launch { jobs = js; status = "${js.size} jobs" } } }) { Text("Jobs") }
                Spacer(Modifier.width(6.dp))
                OutlinedButton(enabled = !busy, onClick = { confirmKill = true }) { Text("Kill PC") }
            }
            if (output.isNotEmpty()) androidx.compose.foundation.text.selection.SelectionContainer {
                Text(output, Modifier.padding(top = 8.dp).testTag("pc_output"))
            }
        }
        items(jobs, key = { it.id }) { j ->
            Text("${j.id} · ${j.mode} · ${j.status}: ${j.prompt.take(80)}", Modifier.padding(vertical = 2.dp))
        }
    }
    if (confirmKill) AlertDialog(onDismissRequest = { confirmKill = false },
        title = { Text("Kill switch on the PC?") }, text = { Text("This stops Kairos on the paired PC.") },
        confirmButton = { TextButton(onClick = { confirmKill = false; io("Sending kill…") { c -> val r = c.kill(); scope.launch { status = r } } }) { Text("Kill") } },
        dismissButton = { TextButton(onClick = { confirmKill = false }) { Text("Cancel") } })
}
