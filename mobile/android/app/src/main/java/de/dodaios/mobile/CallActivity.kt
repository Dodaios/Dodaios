package de.dodaios.mobile

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject

/**
 * A live voice call with Jarvis: microphone PCM (16 kHz) goes up the pinned
 * socket and the reply voice (24 kHz PCM) plays back. Ends on hang-up or when the PC closes.
 */
class CallActivity : AppCompatActivity() {
    private lateinit var state: TextView
    private lateinit var transcript: TextView
    private var socket: WebSocket? = null
    private var recorder: AudioRecord? = null
    @Volatile private var player: AudioTrack? = null
    private var micThread: Thread? = null
    @Volatile private var live = false
    private var ended = false

    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) connect() else end("Ohne Mikrofon-Erlaubnis kein Anruf.")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val pad = (24 * resources.displayMetrics.density).toInt()
        state = TextView(this).apply {
            setTextColor(getColor(R.color.hud_cyan))
            textSize = 22f
            letterSpacing = 0.2f
            gravity = Gravity.CENTER
            text = "VERBINDE …"
        }
        transcript = TextView(this).apply {
            setTextColor(getColor(R.color.hud_text))
            textSize = 16f
            gravity = Gravity.CENTER
            setPadding(0, pad, 0, pad)
        }
        val reactor = RingIndicatorView(this).apply { online = true }
        val hangUp = Button(this).apply {
            text = getString(R.string.hang_up)
            setTextColor(getColor(R.color.hud_gold))
            setBackgroundResource(R.drawable.hud_button)
            setOnClickListener { end(null) }
        }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                setBackgroundColor(getColor(R.color.hud_bg))
                setPadding(pad, pad * 2, pad, pad)
                addView(reactor, LinearLayout.LayoutParams(pad * 6, pad * 6))
                addView(state)
                addView(transcript, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
                addView(
                    hangUp,
                    LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT),
                )
            },
        )
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            connect()
        } else {
            permission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    override fun onDestroy() {
        ended = true
        stopAudio()
        socket?.close(1000, null)
        socket = null
        super.onDestroy()
    }

    private fun connect() {
        val pairing = SecureStore(this).load() ?: return end("Nicht gekoppelt.")
        socket = GatewayClient(pairing.host, pairing.port, pairing.fingerprint).call(pairing.token, listener)
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            webSocket.send(JSONObject().put("type", "audio_start").put("sample_rate", MIC_RATE).toString())
            runOnUiThread {
                if (ended) return@runOnUiThread
                state.text = "VERBUNDEN"
                startAudio(webSocket)
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            val pcm = bytes.toByteArray()
            player?.write(pcm, 0, pcm.size)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val event = runCatching { JSONObject(text) }.getOrNull() ?: return
            runOnUiThread {
                if (ended) return@runOnUiThread
                when (event.optString("type")) {
                    "transcript" -> {
                        val who = if (event.optString("role") == "assistant") "Jarvis" else "Du"
                        transcript.text = "$who: ${event.optString("text")}"
                    }
                    "tts_start" -> state.text = "JARVIS SPRICHT"
                    "audio_ready", "tts_end" -> state.text = "ICH HÖRE ZU"
                    "tts_cancel" -> player?.run { pause(); flush(); play() }
                    "provider_error" -> transcript.text = "Sprachdienst gestört."
                    "hangup" -> end(null)
                }
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            runOnUiThread { end(if (code == 1000) null else "Anruf beendet ($code).") }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val why = when (response?.code) {
                null -> "PC nicht erreichbar."
                401, 403 -> "Gerät nicht (mehr) gekoppelt."
                else -> "Anruf fehlgeschlagen (${response.code})."
            }
            runOnUiThread { end(why) }
        }
    }

    @Suppress("MissingPermission") // granted before connect()
    private fun startAudio(webSocket: WebSocket) {
        getSystemService(AudioManager::class.java).run {
            mode = AudioManager.MODE_IN_COMMUNICATION
            @Suppress("DEPRECATION")
            isSpeakerphoneOn = true
        }

        val outSize = AudioTrack.getMinBufferSize(TTS_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        player = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(TTS_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build(),
            )
            .setBufferSizeInBytes(outSize * 4)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
            .also { it.play() }

        val inSize = maxOf(
            AudioRecord.getMinBufferSize(MIC_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT),
            FRAME_BYTES * 4,
        )
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            MIC_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            inSize,
        )
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            end("Mikrofon nicht verfügbar.")
            return
        }
        if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(rec.audioSessionId)?.enabled = true
        if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId)?.enabled = true
        recorder = rec
        live = true
        rec.startRecording()
        micThread = Thread({
            val frame = ByteArray(FRAME_BYTES)
            while (live) {
                val n = rec.read(frame, 0, frame.size)
                if (n > 0 && !webSocket.send(frame.toByteString(0, n))) break
            }
        }, "call-mic").also { it.start() }
    }

    private fun stopAudio() {
        live = false
        micThread?.join(500)
        micThread = null
        recorder?.run { runCatching { stop() }; release() }
        recorder = null
        player?.run { runCatching { stop() }; release() }
        player = null
        getSystemService(AudioManager::class.java).run {
            @Suppress("DEPRECATION")
            isSpeakerphoneOn = false
            mode = AudioManager.MODE_NORMAL
        }
    }

    private fun end(message: String?) {
        if (ended) return
        ended = true
        stopAudio()
        socket?.close(1000, null)
        socket = null
        if (message != null) Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        finish()
    }

    private companion object {
        const val MIC_RATE = 16000
        const val TTS_RATE = 24000
        const val FRAME_BYTES = 640 // 20 ms of 16 kHz mono PCM16
    }
}
