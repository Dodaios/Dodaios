# Telephony — call Dodaios on a phone number

Dodaios can answer a real phone call. A caller dials a Twilio number and talks to
Dodaios through the same **realtime speech-to-speech** engine every voice
conversation runs on (API Keys > Live calls). Nothing about the voice changes
between the desk and the phone.

Under the hood the call audio is bridged with **Twilio Media Streams** (raw
audio over a WebSocket), not Twilio's ConversationRelay. Media Streams is the
only mode that lets Dodaios's own realtime voice hear the caller and answer in
its own voice — ConversationRelay would force Twilio's speech and voices, so it
is disqualified (design decision AD-T1).

**Which realtime connections can take a call.** A phone line carries plain
audio, so the connection has to take that audio itself. A connection that needs
a browser to set up its audio (a WebRTC offer, such as the GPT-Live connections)
cannot serve a phone line. When no connection that can is set up, Twilio tells
the caller so and hangs up; a call never falls back to another voice engine.

> **Cloud-first.** The telephony feature is an **optional extra**
> (`pip install -e .[telephony]`). The base install boots without it, and the
> Telephony section in the app degrades gracefully (a clear "feature disabled"
> message, never a crash) when the `twilio` package is absent.

---

## What you need

1. A **Twilio account** with a **voice-capable phone number**.
2. A **public HTTPS URL** that Twilio can reach. Two paths, in order of
   preference:
   - **VPS (recommended, cloud-first):** a domain pointing at your VPS, with
     Caddy or another reverse proxy terminating TLS via Let's Encrypt.
   - **Home PC (development):** a tunnel (cloudflared / ngrok) that exposes the
     local FastAPI port.
3. Your Twilio **Auth Token** stored in the credential manager (the setup
   wizard does this).

---

## 1. Install the extra

Already included if you used the official installer or `.[full]` (the one
advertised profile ships telephony). For a minimal base install, add it:

```bash
pip install -e .[telephony]
pip install -e . --no-deps   # refresh entry points
```

On Python 3.13+ this also pulls in `audioop-lts` (the mu-law transcode backport,
since `audioop` left the stdlib). On Python 3.11/3.12 `audioop` is built in.

## 2. Store the Auth Token

```bash
python -m dodaios --wizard
```

The wizard lists **Twilio Auth Token** among the secrets. It is stored in the
Windows Credential Manager (service `dodaios`, key `twilio_auth_token`; earlier
versions used `personal-jarvis`), never in `dodaios.toml`. You can also set the `TWILIO_AUTH_TOKEN` environment
variable.

## 3. Configure the number (VPS path — recommended)

Deploy Dodaios on a VPS and put a reverse proxy in front of the FastAPI port
(default `8765`). A minimal **Caddyfile** that terminates TLS and proxies both
the HTTP webhook and the WebSocket:

```
dodaios.example.com {
    reverse_proxy localhost:8765
}
```

Caddy handles the WebSocket upgrade for `/api/telephony/media` automatically and
gets a Let's Encrypt certificate for `dodaios.example.com` on first start.

Then in the app's **Telephony** section (or in `dodaios.toml`) set:

```toml
[integrations.twilio]
enabled = true
account_sid = "AC..."                # your Account SID (not a secret)
phone_number = "+49301234567"        # your Twilio number, E.164
allowed_callers = ["+4915112345678"] # the numbers that may call in (yours)
public_base_url = "https://dodaios.example.com"   # no trailing slash
language_code = "de-DE"
greeting = ""                        # empty = default greeting with the assistant name
max_call_seconds = 600
```

**Who may call.** A call to the number is a conversation with the assistant
and its tools, and anyone can dial a number. Only the numbers in
`allowed_callers` (**Numbers that may call** in the Telephony section) get
through; every other caller is hung up on. An empty list takes no inbound
call. Calls the app places itself are not affected. A caller's number is
reported by the phone network and can be forged by a determined caller, so
treat the list as a filter against strangers, not as proof of who is calling.

Finally point the number's **Voice webhook** at Dodaios:

```bash
python scripts/telephony_provision.py set-webhook \
    --number +49301234567 \
    --url https://dodaios.example.com/api/telephony/voice
```

(or set the webhook to `POST {public_base_url}/api/telephony/voice` in the
Twilio console.)

## 3-alt. Configure the number (home-PC path — development)

Start a tunnel to the local port and copy the public URL it prints:

```powershell
pwsh scripts/telephony-tunnel.ps1 -Port 8765
# or:  pwsh scripts/telephony-tunnel.ps1 -Port 8765 -Provider ngrok
```

Paste the `https://…` URL into **Public base URL**, then run the
`set-webhook` command above with that URL. Note: a free-tunnel URL changes every
restart, so re-run `set-webhook` each time. The VPS path avoids this.

## 4. Verify and call

- In the Telephony section, click **Test connection** (calls the Twilio REST API
  to confirm the Auth Token), then **Self-test voice** (checks, without a call,
  that a realtime connection that can serve a phone line is ready).
- Call your Twilio number. Dodaios greets you, you talk, it answers in its
  realtime voice. Ask it to hang up, or just hang up yourself, to end the call;
  barge-in is supported (start talking while Dodaios is speaking and it stops to
  listen).

Recent calls appear in the **Recent calls** table.

---

## German +49 numbers — regulatory note

Twilio requires a **regulatory bundle** (an address + identity document, and for
some number types a local-presence proof) before it will provision a German
`+49` number. Allow a day or two for Twilio to approve the bundle. A US/UK
number works immediately for testing if you just want to prove the chain.

## Trial-account caveats

On a Twilio **trial** account:
- You can only call **verified** caller IDs.
- Twilio prepends a trial notice to the call.
- Balance is limited.

Upgrade to a paid account for unrestricted inbound calls.

---

## How it works (for maintainers)

```
Caller -> Twilio number
       -> POST /api/telephony/voice         (signed webhook; we validate
                                              X-Twilio-Signature against the
                                              PUBLIC url, then mint a per-call
                                              secret and return TwiML)
       -> <Connect><Stream wss://…/api/telephony/media>  (bidirectional)
       -> WS /api/telephony/media           (validates the per-call secret,
                                              then starts a realtime session)

caller:    inbound mu-law 8 kHz -> linear PCM 8 kHz -> realtime session
           (the session resamples to its provider's rate)
answer:    realtime session PCM (provider rate) -> resample 8 kHz -> volume
           -> mu-law -> Twilio media + mark -> Twilio plays it to the caller
barge-in:  the session cancels its answer -> Twilio "clear" drops the rest
```

- Each call gets its **own** realtime session (`surface="phone"`): it never takes
  over the desktop's voice call, never follows the desk microphone's mute and
  never starts from the desk conversation. The session's instructions carry a
  brief of the call: who is on the line and, for a call Dodaios placed, its
  purpose. A call to someone else is told not to share the owner's private
  information or act on that person's requests.
- A call placed for one decision (`dodaios/telephony/decision_calls.py`) reads
  the owner's spoken yes / no / later from the session's transcript, settles the
  card, has the voice say the outcome, and hangs up.
- The path never imports `sounddevice` or `SpeechPipeline` — it runs headless on
  a VPS with no audio hardware.
- Modules: `dodaios/telephony/` (audio, call, twiml, security, provisioning,
  status, events, constants, decision_calls) +
  `dodaios/ui/web/telephony_routes.py`.

### Probe without a phone

```bash
python scripts/probe_telephony_e2e.py
```

drives the call bridge with synthetic frames against a fake realtime session
and prints what reached the session and the outbound mu-law chunk count — the
in-repo proof of the transcode and the call lifecycle.

### REST API

Base path `/api/telephony`. UI-facing: `GET /status`, `GET/POST /config`,
`POST /credentials`, `POST /test`, `POST /selftest`, `GET /calls`,
`GET /scripts`. Twilio-facing: `POST /voice`, `WS /media`.
