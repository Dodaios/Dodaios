package de.dodaios.mobile

import org.json.JSONObject

/** Contents of the PC's pairing QR code: `{"v":1,"h":host,"p":port,"f":sha256,"c":code}`. */
data class PairingPayload(val host: String, val port: Int, val fingerprint: String, val code: String) {
    companion object {
        private val FINGERPRINT = Regex("^[0-9a-f]{64}$")

        fun parse(raw: String): PairingPayload? = try {
            val json = JSONObject(raw.trim())
            val payload = PairingPayload(
                host = json.getString("h").trim().removePrefix("[").removeSuffix("]"),
                port = json.getInt("p"),
                fingerprint = json.getString("f").lowercase(),
                code = json.getString("c").trim(),
            )
            val valid = json.optInt("v") == 1 &&
                payload.host.isNotEmpty() &&
                payload.port in 1..65535 &&
                FINGERPRINT.matches(payload.fingerprint) &&
                payload.code.isNotEmpty()
            if (valid) payload else null
        } catch (e: Exception) {
            null
        }
    }
}

/** Where a paired gateway lives and how to prove who we are. */
data class Pairing(val host: String, val port: Int, val fingerprint: String, val token: String)
