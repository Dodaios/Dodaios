package de.dodaios.mobile

import java.io.IOException
import java.io.OutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

class GatewayException(message: String) : IOException(message)

/**
 * Talks to the PC's mobile gateway. Only the one self-signed certificate whose
 * SHA-256 came in the pairing QR code is accepted; anything else fails the handshake.
 */
class GatewayClient(private val host: String, private val port: Int, fingerprint: String) {
    private val pin = fingerprint.lowercase()

    private val trustManager = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
            throw CertificateException("client certificates are not used")
        }

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            val leaf = chain.firstOrNull() ?: throw CertificateException("no certificate")
            if (sha256(leaf.encoded) != pin) throw CertificateException("certificate does not match pairing")
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    private val http: OkHttpClient = OkHttpClient.Builder()
        .sslSocketFactory(
            SSLContext.getInstance("TLS").apply { init(null, arrayOf(trustManager), SecureRandom()) }.socketFactory,
            trustManager,
        )
        // The certificate carries no name for a home IPv6 that may change; the pin is the identity check.
        .hostnameVerifier { _, session ->
            val leaf = session.peerCertificates.firstOrNull() as? X509Certificate
            leaf != null && sha256(leaf.encoded) == pin
        }
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    fun pair(code: String, deviceName: String): String {
        val body = JSONObject().put("code", code).put("device_name", deviceName)
        return call(post("pair", body, token = null)).getString("token")
    }

    fun status(token: String): JSONObject = call(get("status", token))

    fun message(token: String, text: String): String =
        call(post("message", JSONObject().put("text", text), token)).getString("reply")

    fun history(token: String): JSONArray = call(get("history?limit=100", token)).getJSONArray("items")

    fun inbox(token: String, after: Long): JSONArray = call(get("inbox?after=$after", token)).getJSONArray("items")

    fun tasks(token: String): JSONArray = call(get("tasks", token)).getJSONArray("items")

    fun addTask(token: String, text: String): JSONObject = call(post("tasks", JSONObject().put("text", text), token))

    fun setTask(token: String, id: String, done: Boolean): JSONObject =
        call(post("tasks/$id", JSONObject().put("done", done), token))

    fun deleteTask(token: String, id: String) {
        call(Request.Builder().url(url("tasks/$id")).delete().header("Authorization", "Bearer $token").build())
    }

    fun projects(token: String): JSONArray = call(get("projects", token)).getJSONArray("items")

    /** Opens a voice call to Jarvis; audio and events arrive on [listener]. */
    fun call(token: String, listener: WebSocketListener): WebSocket =
        http.newBuilder().readTimeout(0, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).build()
            .newWebSocket(get("call", token), listener)

    /** Waits up to [waitSeconds] for Jarvis to ring this phone; the ring or null. */
    fun ring(token: String, waitSeconds: Int = 25): JSONObject? =
        call(get("ring?wait=$waitSeconds", token)).optJSONObject("ring")

    fun files(token: String): JSONArray = call(get("files", token)).getJSONArray("items")

    fun upload(token: String, name: String, data: ByteArray): JSONObject {
        val target = url("files").newBuilder().addQueryParameter("name", name).build()
        return call(
            Request.Builder().url(target).post(data.toRequestBody(BINARY))
                .header("Authorization", "Bearer $token").build(),
        )
    }

    /** Streams one file into [out]. */
    fun download(token: String, which: String, name: String, out: OutputStream) {
        val target = url("files").newBuilder().addPathSegment(which).addPathSegment(name).build()
        val request = Request.Builder().url(target).header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw GatewayException(describe(response.code))
            response.body?.byteStream()?.copyTo(out) ?: throw GatewayException("Leere Antwort")
        }
    }

    private fun url(path: String): HttpUrl {
        val (segments, query) = path.split("?", limit = 2).let { it[0] to it.getOrNull(1) }
        return HttpUrl.Builder()
            .scheme("https")
            .host(host)
            .port(port)
            .addPathSegments("api/m/$segments")
            .query(query)
            .build()
    }

    private fun get(path: String, token: String): Request =
        Request.Builder().url(url(path)).header("Authorization", "Bearer $token").build()

    private fun post(path: String, body: JSONObject, token: String?): Request {
        val builder = Request.Builder()
            .url(url(path))
            .post(body.toString().toRequestBody(JSON))
        if (token != null) builder.header("Authorization", "Bearer $token")
        return builder.build()
    }

    private fun call(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) throw GatewayException(describe(response.code))
            return JSONObject(text)
        }
    }

    private fun describe(code: Int): String = when (code) {
        401 -> "Gerät nicht (mehr) gekoppelt"
        403 -> "Kopplungscode ungültig oder abgelaufen"
        404 -> "Nicht gefunden"
        413 -> "Datei oder Nachricht zu groß"
        422 -> "Ungültige Eingabe"
        429 -> "Zu viele Anfragen, kurz warten"
        504 -> "Jarvis hat nicht rechtzeitig geantwortet"
        else -> "Serverfehler $code"
    }

    private companion object {
        val JSON = "application/json; charset=utf-8".toMediaType()
        val BINARY = "application/octet-stream".toMediaType()

        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
