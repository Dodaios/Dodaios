package de.dodaios.mobile

import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private enum class Tab { CHAT, TASKS, INBOX, FILES, PROJECTS }

    private lateinit var store: SecureStore
    private var pairing: Pairing? = null
    private var tab = Tab.CHAT
    private var poller: Job? = null

    private lateinit var reactor: RingIndicatorView
    private lateinit var status: TextView
    private lateinit var pairPanel: View
    private lateinit var mainPanel: View
    private lateinit var payload: EditText
    private lateinit var sectionTitle: TextView
    private lateinit var scroll: ScrollView
    private lateinit var list: LinearLayout
    private lateinit var inputRow: View
    private lateinit var input: EditText
    private lateinit var action: Button
    private lateinit var tabs: Map<Tab, TextView>

    private val prefs by lazy { getSharedPreferences("app", MODE_PRIVATE) }

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        result.contents?.let {
            payload.setText(it)
            pair(it)
        }
    }

    private val notify = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    private val picker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { upload(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = SecureStore(this)

        reactor = findViewById(R.id.reactor)
        status = findViewById(R.id.status)
        pairPanel = findViewById(R.id.pairPanel)
        mainPanel = findViewById(R.id.mainPanel)
        payload = findViewById(R.id.payload)
        sectionTitle = findViewById(R.id.sectionTitle)
        scroll = findViewById(R.id.scroll)
        list = findViewById(R.id.list)
        inputRow = findViewById(R.id.inputRow)
        input = findViewById(R.id.input)
        action = findViewById(R.id.action)
        tabs = mapOf(
            Tab.CHAT to findViewById(R.id.tabChat),
            Tab.TASKS to findViewById(R.id.tabTasks),
            Tab.INBOX to findViewById(R.id.tabInbox),
            Tab.FILES to findViewById(R.id.tabFiles),
            Tab.PROJECTS to findViewById(R.id.tabProjects),
        )
        tabs.forEach { (t, view) -> view.setOnClickListener { select(t) } }

        findViewById<Button>(R.id.scan).setOnClickListener {
            scanner.launch(
                ScanOptions()
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                    .setPrompt("QR-Code vom PC scannen")
                    .setBeepEnabled(false),
            )
        }
        findViewById<Button>(R.id.pair).setOnClickListener { pair(payload.text.toString()) }
        findViewById<View>(R.id.call).setOnClickListener {
            if (pairing != null) startActivity(android.content.Intent(this, CallActivity::class.java))
        }
        findViewById<View>(R.id.refresh).setOnClickListener {
            refreshStatus()
            load()
        }
        reactor.setOnLongClickListener {
            if (pairing != null) confirmUnpair()
            true
        }
        action.setOnClickListener { onAction() }

        pairing = store.load()
        if (pairing == null) showPairing("Nicht gekoppelt.") else showMain()
    }

    override fun onStart() {
        super.onStart()
        if (pairing != null) {
            refreshStatus()
            startPolling()
        }
    }

    override fun onStop() {
        poller?.cancel()
        super.onStop()
    }

    // -- screens -------------------------------------------------------

    private fun showPairing(text: String) {
        poller?.cancel()
        pairPanel.visibility = View.VISIBLE
        mainPanel.visibility = View.GONE
        reactor.online = false
        status.text = text
    }

    private fun showMain() {
        pairPanel.visibility = View.GONE
        mainPanel.visibility = View.VISIBLE
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            notify.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
        RingService.start(this)
        select(tab)
    }

    private fun select(t: Tab) {
        tab = t
        tabs.forEach { (key, view) ->
            view.isSelected = key == t
            view.setTextColor(getColor(if (key == t) R.color.hud_cyan else R.color.hud_text_dim))
        }
        sectionTitle.text = when (t) {
            Tab.CHAT -> "// KOMMUNIKATION"
            Tab.TASKS -> "// AUFGABEN"
            Tab.INBOX -> "// NACHRICHTEN VON JARVIS"
            Tab.FILES -> "// DATEITRANSFER"
            Tab.PROJECTS -> "// PROJEKTSTATUS"
        }
        inputRow.visibility = if (t == Tab.INBOX || t == Tab.PROJECTS) View.GONE else View.VISIBLE
        input.visibility = if (t == Tab.FILES) View.GONE else View.VISIBLE
        input.hint = if (t == Tab.TASKS) "Neue Aufgabe" else "Nachricht an Jarvis"
        action.text = when (t) {
            Tab.CHAT -> "Senden"
            Tab.TASKS -> "+"
            else -> "Datei hochladen"
        }
        (action.layoutParams as LinearLayout.LayoutParams).apply {
            width = if (t == Tab.FILES) LinearLayout.LayoutParams.MATCH_PARENT else LinearLayout.LayoutParams.WRAP_CONTENT
            marginStart = if (t == Tab.FILES) 0 else dp(8)
            action.layoutParams = this
        }
        if (t == Tab.INBOX) markInboxRead()
        load()
    }

    private fun onAction() = when (tab) {
        Tab.CHAT -> send()
        Tab.TASKS -> addTask()
        Tab.FILES -> picker.launch("*/*")
        Tab.INBOX, Tab.PROJECTS -> Unit
    }

    // -- networking helpers ---------------------------------------------

    private fun client(p: Pairing) = GatewayClient(p.host, p.port, p.fingerprint)

    /** Runs [block] off the main thread; failures land in the status line. */
    private fun <T> request(block: (GatewayClient, String) -> T, onOk: (T) -> Unit) {
        val p = pairing ?: return
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { block(client(p), p.token) } }
                .onSuccess(onOk)
                .onFailure {
                    reactor.busy = false
                    reactor.online = false
                    status.text = "Fehler: ${it.message}"
                }
        }
    }

    private fun pair(raw: String) {
        val parsed = PairingPayload.parse(raw)
        if (parsed == null) {
            status.text = "Kopplungsdaten nicht lesbar."
            return
        }
        status.text = "Kopple mit [${parsed.host}]:${parsed.port} …"
        lifecycleScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    GatewayClient(parsed.host, parsed.port, parsed.fingerprint)
                        .pair(parsed.code, Build.MODEL ?: "Android")
                }
            }.onSuccess { token ->
                val p = Pairing(parsed.host, parsed.port, parsed.fingerprint, token)
                store.save(p)
                pairing = p
                payload.text.clear()
                showMain()
                refreshStatus()
                startPolling()
            }.onFailure { status.text = "Kopplung fehlgeschlagen: ${it.message}" }
        }
    }

    private fun confirmUnpair() {
        AlertDialog.Builder(this)
            .setTitle("Entkoppeln?")
            .setMessage("Am PC lässt sich das Gerät zusätzlich mit 'revoke' widerrufen.")
            .setPositiveButton("Entkoppeln") { _, _ ->
                store.clear()
                RingService.stop(this)
                pairing = null
                showPairing("Entkoppelt.")
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun refreshStatus() {
        status.text = "Verbinde …"
        request({ c, t -> c.status(t) }) {
            reactor.online = true
            status.text = "ONLINE · ${it.optString("device")} · seit ${formatUptime(it.optLong("uptime_s"))}"
        }
    }

    private fun load() {
        when (tab) {
            Tab.CHAT -> request({ c, t -> c.history(t) }) { renderChat(it) }
            Tab.TASKS -> request({ c, t -> c.tasks(t) }) { renderTasks(it) }
            Tab.INBOX -> request({ c, t -> c.inbox(t, 0) }) { renderInbox(it) }
            Tab.FILES -> request({ c, t -> c.files(t) }) { renderFiles(it) }
            Tab.PROJECTS -> request({ c, t -> c.projects(t) }) { renderProjects(it) }
        }
    }

    // -- chat ----------------------------------------------------------

    private fun renderChat(items: JSONArray) {
        list.removeAllViews()
        if (items.length() == 0) placeholder("Noch keine Unterhaltung. Schreib Jarvis etwas.")
        for (i in 0 until items.length()) {
            val item = items.getJSONObject(i)
            bubble(item.optString("text"), item.optString("role") == "user")
        }
        scrollToEnd()
    }

    private fun bubble(text: String, mine: Boolean): TextView {
        val view = TextView(this).apply {
            this.text = text
            setTextColor(getColor(R.color.hud_text))
            textSize = 15f
            setTextIsSelectable(true)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setBackgroundResource(if (mine) R.drawable.bubble_user else R.drawable.bubble_jarvis)
        }
        val label = TextView(this).apply {
            this.text = if (mine) "SIE" else "JARVIS"
            textSize = 10f
            letterSpacing = 0.2f
            setTextColor(getColor(if (mine) R.color.hud_gold else R.color.hud_cyan))
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = if (mine) Gravity.END else Gravity.START
            addView(label)
            addView(view)
        }
        list.addView(
            column,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply {
                    topMargin = dp(10)
                    if (mine) marginStart = dp(48) else marginEnd = dp(48)
                },
        )
        return view
    }

    private fun send() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.text.clear()
        if (list.childCount == 1 && list.getChildAt(0).tag == PLACEHOLDER) list.removeAllViews()
        bubble(text, mine = true)
        val pending = bubble("Analysiere …", mine = false)
        scrollToEnd()
        reactor.busy = true
        action.isEnabled = false
        val p = pairing ?: return
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { client(p).message(p.token, text) } }
                .onSuccess { pending.text = it }
                .onFailure { pending.text = "Fehler: ${it.message}" }
            reactor.busy = false
            action.isEnabled = true
            scrollToEnd()
        }
    }

    // -- tasks ---------------------------------------------------------

    private fun renderTasks(items: JSONArray) {
        list.removeAllViews()
        if (items.length() == 0) placeholder("Keine Aufgaben. Neue unten eintragen.")
        val sorted = (0 until items.length()).map { items.getJSONObject(it) }.sortedBy { it.optBoolean("done") }
        for (task in sorted) taskRow(task)
    }

    private fun taskRow(task: JSONObject) {
        val id = task.optString("id")
        val done = task.optBoolean("done")
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundResource(R.drawable.hud_panel)
            setPadding(dp(8), dp(4), dp(4), dp(4))
        }
        val check = CheckBox(this).apply {
            isChecked = done
            buttonTintList = getColorStateList(R.color.hud_cyan)
            setOnCheckedChangeListener { _, checked ->
                request({ c, t -> c.setTask(t, id, checked) }) { load() }
            }
        }
        val text = TextView(this).apply {
            this.text = task.optString("text")
            textSize = 15f
            setTextColor(getColor(if (done) R.color.hud_text_dim else R.color.hud_text))
            if (done) paintFlags = paintFlags or android.graphics.Paint.STRIKE_THRU_TEXT_FLAG
        }
        val delete = TextView(this).apply {
            this.text = "✕"
            textSize = 18f
            gravity = Gravity.CENTER
            setTextColor(getColor(R.color.hud_red))
            setPadding(dp(12), dp(8), dp(12), dp(8))
            setOnClickListener { request({ c, t -> c.deleteTask(t, id) }) { load() } }
        }
        row.addView(check)
        row.addView(text, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(delete)
        addRow(row)
    }

    private fun addTask() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.text.clear()
        request({ c, t -> c.addTask(t, text) }) { load() }
    }

    // -- inbox ---------------------------------------------------------

    private fun renderInbox(items: JSONArray) {
        list.removeAllViews()
        if (items.length() == 0) placeholder("Keine Nachrichten von Jarvis.")
        for (i in items.length() - 1 downTo 0) {
            val item = items.getJSONObject(i)
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundResource(R.drawable.hud_panel)
                setPadding(dp(12), dp(10), dp(12), dp(12))
            }
            card.addView(
                TextView(this).apply {
                    text = formatTime(item.optLong("ts"))
                    textSize = 10f
                    setTextColor(getColor(R.color.hud_gold))
                },
            )
            card.addView(
                TextView(this).apply {
                    text = item.optString("text")
                    textSize = 15f
                    setTextIsSelectable(true)
                    setTextColor(getColor(R.color.hud_text))
                },
            )
            addRow(card)
        }
        markInboxRead(items)
    }

    private fun renderProjects(items: JSONArray) {
        list.removeAllViews()
        if (items.length() == 0) placeholder("Keine Missionen auf dem PC.")
        for (i in 0 until items.length()) {
            val item = items.getJSONObject(i)
            val active = item.optBoolean("active")
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundResource(R.drawable.hud_panel)
                setPadding(dp(12), dp(10), dp(12), dp(12))
            }
            card.addView(
                TextView(this).apply {
                    text = "${stateLabel(item.optString("state"))}  ·  ${formatTime(item.optLong("updated_ms") / 1000)}"
                    textSize = 10f
                    setTextColor(getColor(if (active) R.color.hud_cyan else R.color.hud_gold))
                },
            )
            card.addView(
                TextView(this).apply {
                    text = item.optString("title")
                    textSize = 15f
                    setTextIsSelectable(true)
                    setTextColor(getColor(R.color.hud_text))
                },
            )
            addRow(card)
        }
    }

    private fun stateLabel(state: String): String = when (state) {
        "PENDING" -> "WARTET"
        "RUNNING" -> "LÄUFT"
        "CRITIQUING" -> "WIRD GEPRÜFT"
        "LOOPING" -> "NEUER ANLAUF"
        "WAITING_CAPACITY" -> "WARTET AUF KAPAZITÄT"
        "APPROVED" -> "FERTIG"
        "FAILED" -> "FEHLGESCHLAGEN"
        "CANCELLED" -> "ABGEBROCHEN"
        "TIMED_OUT" -> "ZEIT ÜBERSCHRITTEN"
        else -> state
    }

    private fun markInboxRead(items: JSONArray? = null) {
        val last = items?.let { if (it.length() > 0) it.getJSONObject(it.length() - 1).optLong("id") else null }
        if (last != null) prefs.edit().putLong(KEY_LAST_INBOX, last).apply()
        tabs.getValue(Tab.INBOX).text = getString(R.string.tab_inbox)
    }

    private fun startPolling() {
        poller?.cancel()
        poller = lifecycleScope.launch {
            while (isActive) {
                val p = pairing ?: break
                val after = prefs.getLong(KEY_LAST_INBOX, 0)
                runCatching { withContext(Dispatchers.IO) { client(p).inbox(p.token, after) } }
                    .onSuccess { fresh ->
                        reactor.online = true
                        if (fresh.length() > 0) {
                            if (tab == Tab.INBOX) {
                                load()
                            } else {
                                tabs.getValue(Tab.INBOX).text = "${getString(R.string.tab_inbox)} •${fresh.length()}"
                            }
                        }
                    }
                delay(POLL_MS)
            }
        }
    }

    // -- files ---------------------------------------------------------

    private fun renderFiles(items: JSONArray) {
        list.removeAllViews()
        val all = (0 until items.length()).map { items.getJSONObject(it) }
        section("VOM PC ZUM HANDY", all.filter { it.optString("dir") == "to_phone" }, download = true)
        section("VOM HANDY HOCHGELADEN", all.filter { it.optString("dir") == "from_phone" }, download = false)
    }

    private fun section(title: String, files: List<JSONObject>, download: Boolean) {
        list.addView(
            TextView(this).apply {
                text = title
                textSize = 11f
                letterSpacing = 0.15f
                setTextColor(getColor(R.color.hud_gold))
                setPadding(0, dp(12), 0, dp(4))
            },
        )
        if (files.isEmpty()) placeholder("— leer —")
        for (file in files) {
            val name = file.optString("name")
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundResource(R.drawable.hud_panel)
                setPadding(dp(12), dp(10), dp(12), dp(10))
                if (download) setOnClickListener { download(file.optString("dir"), name) }
            }
            row.addView(
                TextView(this).apply {
                    text = if (download) "⬇  $name" else name
                    textSize = 15f
                    setTextColor(getColor(if (download) R.color.hud_cyan else R.color.hud_text))
                },
            )
            row.addView(
                TextView(this).apply {
                    text = "${formatSize(file.optLong("size"))} · ${formatTime(file.optLong("mtime"))}"
                    textSize = 11f
                    setTextColor(getColor(R.color.hud_text_dim))
                },
            )
            addRow(row)
        }
    }

    private fun upload(uri: Uri) {
        val name = contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
        } ?: "datei"
        status.text = "Lade $name hoch …"
        reactor.busy = true
        request({ c, t ->
            val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                ?: throw GatewayException("Datei nicht lesbar")
            if (bytes.size > MAX_UPLOAD) throw GatewayException("Datei zu groß (max. 25 MB)")
            c.upload(t, name, bytes)
        }) {
            reactor.busy = false
            status.text = "Hochgeladen: ${it.optString("name")}"
            load()
        }
    }

    private fun download(which: String, name: String) {
        status.text = "Lade $name …"
        reactor.busy = true
        request({ c, t ->
            openDownload(name).use { (out, where) ->
                c.download(t, which, name, out)
                where
            }
        }) {
            reactor.busy = false
            status.text = "Gespeichert: $it"
            Toast.makeText(this, "Gespeichert in $it", Toast.LENGTH_LONG).show()
        }
    }

    /** A stream into the public Downloads folder (API 29+) or the app's own one. */
    private fun openDownload(name: String): Target {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Dodaios")
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw GatewayException("Download-Ordner nicht verfügbar")
            val out = contentResolver.openOutputStream(uri) ?: throw GatewayException("Download-Ordner nicht verfügbar")
            return Target(out, "Downloads/Dodaios/$name")
        }
        val dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
        val file = File(dir, name)
        return Target(FileOutputStream(file), file.absolutePath)
    }

    private class Target(val out: OutputStream, val where: String) : AutoCloseable {
        operator fun component1() = out
        operator fun component2() = where
        override fun close() = out.close()
    }

    // -- view helpers --------------------------------------------------

    private fun addRow(view: View) {
        list.addView(
            view,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(8) },
        )
    }

    private fun placeholder(text: String) {
        list.addView(
            TextView(this).apply {
                this.text = text
                tag = PLACEHOLDER
                setTextColor(getColor(R.color.hud_text_dim))
                setPadding(dp(4), dp(16), dp(4), dp(16))
            },
        )
    }

    private fun scrollToEnd() = scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun formatUptime(seconds: Long): String {
        val h = seconds / 3600
        val m = (seconds % 3600) / 60
        return if (h > 0) "$h h $m min" else "$m min"
    }

    private fun formatTime(epoch: Long): String =
        SimpleDateFormat("dd.MM. HH:mm", Locale.GERMANY).format(Date(epoch * 1000))

    private fun formatSize(bytes: Long): String = when {
        bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
        bytes >= 1024 -> "${bytes / 1024} KB"
        else -> "$bytes B"
    }

    private companion object {
        const val PLACEHOLDER = "placeholder"
        const val KEY_LAST_INBOX = "last_inbox"
        const val POLL_MS = 15_000L
        const val MAX_UPLOAD = 25 * 1024 * 1024
    }
}
