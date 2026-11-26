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
            onDone = { _, r -> main.post { messages[idx] = UiMsg("assistant", r as String); finish() } },
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
            TopAppBar(title = { Text("KAIROS") }, actions = {
                TextButton(onClick = { tab = 7 }, modifier = Modifier.testTag("tab_Skills")) { Text("Skills") }
                TextButton(onClick = { tab = 6 }, modifier = Modifier.testTag("tab_Connect")) { Text("Email & Telegram") }
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
                else -> SkillsScreen(app)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
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
                placeholder = { Text("Message Kairos (/help for commands)") })
            Spacer(Modifier.width(6.dp))
            Button(onClick = { vm.send(input); input = "" }, modifier = Modifier.testTag("send")) {
                Text("Send")
            }
        }
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            listOf("chat" to "Chat", "plan" to "Plan", "execute" to "Execute").forEach { (id, label) ->
                FilterChip(selected = vm.mode == id, onClick = { vm.mode = id }, label = { Text(label) },
                    modifier = Modifier.padding(end = 6.dp).testTag("mode_$id"))
            }
            if (vm.busy) Text("working…", Modifier.testTag("busy"))
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
