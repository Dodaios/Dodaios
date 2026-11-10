# The phone companion

The lead keeps one endless conversation (ADR-0045). This feature puts that
conversation on the person's phone: read it, type into it, approve what waits,
send a voice note, and get a push when something needs them. Nothing is a
second conversation; the phone sees the same session the desktop shows.

Three pieces, in the order they are useful:

1. **The phone app** at `/m/`: an installable web app (manifest, icons, service
   worker) with its own tiny bundle (`frontend/m/index.html`, `src/mobile/*`,
   ~25 KB of JavaScript). It shares no module with the desktop entry, so the
   desktop's startup bundle is unchanged.
2. **Web push** to the paired phone: needs-you cards (approvals, questions,
   credentials, proposals) and the lead's reminders.
3. **WhatsApp**, owner-only: the person's own chat with the assistant continues
   the lead conversation like the Telegram private chat does. Shipped as a
   channel adapter behind a flag; the linked-device bridge is the missing part
   (see below).

## Pairing and access

There is no open access. Every phone call to `/api/mobile/app/*` carries a
device token (`Authorization: Bearer mdt_...`), and only that prefix accepts it
(`SurfaceSecurity._mobile_token_accepted`). The token never opens the desktop
routes, the Control API or a WebSocket.

Flow:

1. **Settings → Phone → Show pairing code.** The desktop mints a ten-character
   code (`POST /api/mobile/pair/code`, desktop credentials only). It lives five
   minutes in memory and works once. Twenty wrong guesses drop every open code.
2. The code is shown as a QR that carries `http://<lan-ip>:<port>/m/#pair=CODE`.
   The code travels in the URL fragment, so it never reaches a server log.
3. The phone opens the link (or types the code), and `POST /api/mobile/pair/redeem`
   answers once with the device token. Only the token's SHA-256 digest is
   stored (`<data dir>/mobile/devices.json`); the phone keeps the token in its
   browser storage.
4. **Settings → Phone → Paired phones** lists every device (name, paired,
   last seen, notifications on/off). **Remove** revokes it: the next call from
   that phone answers 401 and its push subscription is deleted. The phone can
   also unpair itself from its menu.

Transport rule: HTTPS anywhere; plain HTTP only from a private (LAN) or
loopback address. From a public address over plain HTTP, pairing and every
phone route answer 403.

### Reaching the computer from the phone

The desktop app listens on `127.0.0.1` by default; a phone cannot reach that.
For the LAN case start the app with `JARVIS_BIND_HOST=0.0.0.0` **and** a
control key (`assert_bind_safe` refuses a network bind without one; see
`docs/dodaios-control-api.md`). The Phone page says so and offers no code
while the bind is loopback-only. A settings switch for "listen on my network"
is a reasonable follow-up; it belongs to the launcher, not to this feature.

Remote access (outside the home network) is the existing Computers story: an
independent server reached over HTTPS (`docs/server-pairing.md`,
`docs/headless-vps-deployment.md`). The phone companion works on any origin the
app is served from; on HTTPS it also installs and receives pushes.

### What works where

| Served over | Read / type / approve / voice note | Add to home screen | Push |
| --- | --- | --- | --- |
| LAN, plain HTTP | yes | browser bookmark only | no (needs a secure context) |
| HTTPS (tunnel, reverse proxy, paired server) | yes | yes | yes |

Service workers and the Push API need a secure context, so over plain LAN HTTP
the page is just a page. The app says this on its pairing screen and in
Settings; nothing pretends otherwise.

## The phone app

`GET /m/` serves `dist/m/index.html`. The app:

- reads `#pair=CODE`, removes it from the address and redeems it;
- polls `GET /api/mobile/app/lead?tail=160`, which returns the conversation
  folded into phone rows (`dodaios/mobile/timeline.py`: user, assistant,
  approval, question, notice, error) plus `pending_approvals`, `waiting`,
  `running`; every 2.5 s while a turn runs or something waits, every 7 s when
  idle, never while the page is hidden; a push nudges it to refresh;
- sends typed text with `POST /api/mobile/app/lead/messages` (the same
  `send_or_queue` as the desktop: a running turn queues the message);
- answers approval cards with `POST .../approvals/{id}` (`allow` or `deny`,
  never a standing rule; questions are shown and answered on the desktop);
- records a voice note with the phone's microphone, decodes and resamples it
  in the browser to 16 kHz mono int16 PCM and posts it to
  `POST .../lead/voice-note`; the computer transcribes it with the dictation
  lane's recognizer (local first) and sends the text. Without a recognizer the
  phone is told so (503);
- turns push on and off from its menu (`PUT/DELETE .../push/subscription`).

The phone's strings are the `mobile.app` namespace of the five locale files,
inlined at build time by the `mobileStrings` Vite plugin (`virtual:mobile-strings`)
so the phone bundle never imports the desktop's locale JSON.

## Web push

`dodaios/mobile/webpush.py` implements VAPID (RFC 8292) and `aes128gcm`
payload encryption (RFC 8291) on `cryptography`, which is already a base
dependency, so no extra package has to install anywhere.

- The VAPID key pair is generated on first use and kept at
  `<data dir>/mobile/vapid.json` (mode 0600 where the OS honours it). It is
  per installation and never part of the repository.
- `dodaios/mobile/notify.py` listens to two sources: `AgentAttentionChanged`
  with `transition == "needs_input"` (the attention module already decided the
  change is worth telling: never unattended work, never while the person looks
  at that agent, throttled) and `notice` events in the lead conversation whose
  kind is a reminder or a result the person asked for
  (`REMINDER_NOTICE_KINDS`) or that carry `push: true`.
- The same card or notice is pushed at most once per 90 s. A subscription the
  push service reports gone (404/410) is dropped from the device record.
- Nothing is spoken, and no model runs for a push.

`POST /api/mobile/app/push/test` sends one test note so the person sees the
path work.

## WhatsApp (owner only, behind a flag)

The person wants their **own** WhatsApp (a linked device, like WhatsApp Web),
not a business number. `dodaios/channels/whatsapp.py` ships the channel the
way Telegram is built:

- off by default (`<data dir>/mobile/whatsapp.json` `enabled`, or
  `DODAIOS_WHATSAPP_ENABLED=1`); a disabled channel starts silently so the
  channel manager stays green; the Settings switch writes the flag and takes
  effect on the next start;
- exactly one sender is answered: the owner. The first private message within
  the ten-minute pairing window after the channel comes up claims the owner
  seat (persisted); everybody else, groups and broadcasts are dropped without
  a reply;
- the chat bridge (`chat_bridge._lead_service`) routes the owner's private
  chat into the lead conversation and sends the answer back to the same chat,
  exactly as the Telegram private chat does;
- the channel speaks to a **local bridge process** over a small HTTP contract
  (`BridgeTransport`): `GET /status` → `{"linked", "me"}`,
  `GET /messages?wait=25` (long poll) → `{"messages": [{"id", "from", "text",
  "private", "ts"}]}`, `POST /send` `{"to", "text"}`. The bridge holds the
  WhatsApp session; this process never sees its keys.

**What is missing: the bridge.** There is no maintained Python library for the
linked-device protocol that does not ship a native binary of its own, the
official Cloud API needs a business phone number (excluded), and the
browser-automation route runs a hidden browser on the person's machine (ruled
out for this product). So the adapter is complete and tested against a fake
transport, and `enabled=true` starts it in a "waiting for the bridge" state
that Settings reports honestly. A bridge candidate must: run locally, expose
the contract above, keep the session on disk the person controls, and show the
linking QR itself. When one is chosen, nothing in this adapter needs to change.

## Files

- `dodaios/mobile/devices.py` — pairing codes, device tokens (digests only),
  push subscriptions, revoke.
- `dodaios/mobile/webpush.py` — VAPID keys, payload encryption, sender.
- `dodaios/mobile/notify.py` — what gets pushed and when.
- `dodaios/mobile/timeline.py` — the lead log folded for a phone.
- `dodaios/ui/web/mobile_routes.py` — desktop and phone routes, `/m/`.
- `dodaios/ui/web/surface_security.py` — device tokens accepted for
  `/api/mobile/app/*` only; `POST /api/mobile/pair/redeem` authenticates inside
  the handler.
- `dodaios/channels/whatsapp.py` — the owner-only channel and bridge contract.
- `frontend/m/index.html`, `frontend/public/m/*`, `frontend/src/mobile/*` — the
  phone app; `frontend/src/views/PhoneView.tsx` — Settings → Phone.
