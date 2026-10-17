package de.dodaios.mobile

import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {
    private lateinit var store: SecureStore
    private var pairing: Pairing? = null

    private lateinit var status: TextView
    private lateinit var pairPanel: View
    private lateinit var chatPanel: View
    private lateinit var payload: EditText
    private lateinit var message: EditText
    private lateinit var reply: TextView

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        result.contents?.let {
            payload.setText(it)
            pair(it)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = SecureStore(this)

        status = findViewById(R.id.status)
        pairPanel = findViewById(R.id.pairPanel)
        chatPanel = findViewById(R.id.chatPanel)
        payload = findViewById(R.id.payload)
        message = findViewById(R.id.message)
        reply = findViewById(R.id.reply)

        findViewById<Button>(R.id.scan).setOnClickListener {
            scanner.launch(
                ScanOptions()
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                    .setPrompt("QR-Code vom PC scannen")
                    .setBeepEnabled(false),
            )
        }
        findViewById<Button>(R.id.pair).setOnClickListener { pair(payload.text.toString()) }
        findViewById<Button>(R.id.refresh).setOnClickListener { refreshStatus() }
        findViewById<Button>(R.id.send).setOnClickListener { send() }
        findViewById<Button>(R.id.unpair).setOnClickListener {
            store.clear()
            pairing = null
            showPairing("Entkoppelt. Am PC lässt sich das Gerät mit 'revoke' widerrufen.")
        }

        pairing = store.load()
        if (pairing == null) {
            showPairing("Nicht gekoppelt.")
        } else {
            showChat()
            refreshStatus()
        }
    }

    private fun showPairing(text: String) {
        pairPanel.visibility = View.VISIBLE
        chatPanel.visibility = View.GONE
        status.text = text
    }

    private fun showChat() {
        pairPanel.visibility = View.GONE
        chatPanel.visibility = View.VISIBLE
    }

    private fun client(p: Pairing) = GatewayClient(p.host, p.port, p.fingerprint)

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
                showChat()
                refreshStatus()
            }.onFailure { status.text = "Kopplung fehlgeschlagen: ${it.message}" }
        }
    }

    private fun refreshStatus() {
        val p = pairing ?: return
        status.text = "Verbinde …"
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { client(p).status(p.token) } }
                .onSuccess {
                    status.text = "${it.optString("server")} online · Gerät: ${it.optString("device")} · " +
                        "läuft seit ${formatUptime(it.optLong("uptime_s"))}"
                }
                .onFailure { status.text = "Nicht erreichbar: ${it.message}" }
        }
    }

    private fun send() {
        val p = pairing ?: return
        val text = message.text.toString().trim()
        if (text.isEmpty()) return
        reply.text = "Jarvis denkt nach …"
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { client(p).message(p.token, text) } }
                .onSuccess {
                    message.text.clear()
                    reply.text = it
                }
                .onFailure { reply.text = "Fehler: ${it.message}" }
        }
    }

    private fun formatUptime(seconds: Long): String {
        val h = seconds / 3600
        val m = (seconds % 3600) / 60
        return if (h > 0) "$h h $m min" else "$m min"
    }
}
