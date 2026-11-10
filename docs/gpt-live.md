# Continuous voice

GPT-Live is an experimental voice path with a separately selected Responses
thinking model. Both use the same OpenAI credential. Voice duration and backend
tokens are accounted for separately. The application does not enable cloud
recording (`store: false`).

## Settings and migration

Select the voice, thinking model, reasoning effort and web search in API Keys.
Saving creates a pre-migration configuration backup and applies to the next
call. A model is never chosen or upgraded automatically. Gemini/Vertex and local
realtime remain available. Provider-specific function schemas are translated at
the adapter boundary.

Text chat and background work follow the active Agents selection. The OpenAI
voice thinking model is also used for voice-triggered computer control without
another model key. Connected services retain their own credentials.

Voice setup is a single provider panel with a shared credential, conversation
settings and thinking/tool settings. Inspecting a provider does not activate it;
the Live profile saves its provider and model together. The separate Tool Model
tab and inline computer-control model pickers are removed. Saving only refreshes
the affected voice queries and preserves a draft when a key becomes available.

## Execution and media

The `dodaios/live` package separates the provider connection, transcript stream,
tool receipts and execution. GPT-Live uses WebRTC media plus a server-side
control connection, or a primary WebSocket for server audio integrations.
Browser/WebView capture owns echo cancellation; the voice engine does not mute
the microphone merely because it is speaking.

Tool execution remains behind the supervisor gateway and ToolExecutor. The
Responses adapter retains complete function calls, sends all required outputs
and explicitly continues the response. Discovery keeps tools reachable beyond
the initial declaration set. Screenshots enter a vision-capable backend as
images, with existing privacy settings enforced at capture.

Operation receipts prevent the same call ID from executing twice. Uncertain
results are not retried automatically. Confirmations belong to the application,
and already-started work can finish after speech closes. Subscription tasks use
the same gateway with a scoped tool grant; unsupported isolation is reported
instead of silently using another account.

An explicit task cancellation invalidates queued calls and pending approvals.
The next user request gets a new cancellation token, while interrupted work
retains its cancelled token. Scheduled turns keep their starting agent selection
through settings changes, including nested computer-control calls.

Transcripts keep their original fragments and timestamps. The legacy archive
stores one compatibility group at close, not a fabricated provider turn boundary.
Voice duration updates are cumulative snapshots. Backend completion, generated
speech and actual playback are separate states.

## WebRTC wire limits

SDP offers and answers retain their terminal CRLF through browser and server
validation. Trimming an otherwise valid offer was reproduced as HTTP 400 from
Live, while the unchanged offer was accepted.

The initial tool declarations have both a count and a 24 KB JSON budget. A count
limit alone allowed large imported schemas to overflow a 64 KiB RTC data-channel
message before `session.started`. Discovery returns pages with `next_offset`;
the full catalog remains reachable through discovery and `call_tool`.

## Start failures

A call that cannot start names its cause. The classifier is
`dodaios/live/start_failure.py`. It returns only fixed, authored sentences:
the plan does not offer voice, the login expired, the allowance is exhausted,
the API key was rejected or has no credit, the network was unreachable, or
Dodaios tools are still starting. A provider body, a credential or a URL never
reaches the surface. An unknown failure keeps the generic line.

The page names failures on the device the same way: no microphone, a busy
microphone, a refused permission, a blocked audio connection (firewall or VPN)
and a start timeout each have their own sentence.

Signing in proves a login, not voice access. A call start records what it
learned about the account in `live_subscription_voice.json` in the data
directory. The settings page then shows "verified", "unverified" or
"unavailable" with the reason, and does not show "Saved & active" for an
account the voice route refused. The record explains and never gates: every
call still asks the server, and a new login or a changed plan makes an old
record stop matching.

Saving GPT-Live retires a classic voice profile left in `voice.profile`. Boot
repairs a config that still has both. With both set, no realtime session was
built and every call ended at once.

A call whose connection is lost and whose two replacement sessions failed ends
with an error. Before, it stayed "connecting" and held the microphone until a
manual hang-up.

The page asks translators to leave it alone (`translate="no"`), and
`lib/domMutationGuard.ts` keeps React alive when a translator or extension
rewrites nodes anyway. A translated page used to crash with
"Failed to execute 'insertBefore' on 'Node'".

## Qualification

Synthetic live API probes have exercised tool execution, response continuation
and spoken results on OpenAI and Gemini. Contract tests run on Windows and in a
headless Python 3.11 Linux container. A fresh base wheel installation on
`python:3.11-slim` boots a healthy API without PortAudio. An isolated OpenAI
synthetic probe using exactly one credential also passes there, including a
forced reconnect and exactly one tool execution. These checks do not establish
native audio parity or release readiness. Native-device audio, fresh desktop
installations, long-session recovery and comparative latency still require qualification.

Safe transport failures reconnect with jitter and a shared connection budget.
Recovery restores bounded conversation history and completed tool receipts;
it never replays buffered microphone audio. New actions wait for fresh user
input. Pending approvals, running actions or uncertain outcomes prevent automatic
reconnection. Missing final usage remains marked unconfirmed across reconnects.

Synthetic OpenAI and Gemini probes have recovered from forced connection loss,
spoken the previous verified result and kept the tool execution count at one.
These probes do not replace long-call or native-device qualification.

Run `python scripts/verify_gpt_live.py --run-live` for the opt-in OpenAI synthetic
probe. The test uses configured credentials and incurs normal API usage; it
captures neither microphone nor screen data. Gemini is selectable with
`--provider gemini --model gemini-3.1-flash-live-preview`.
Add `--reconnect` to verify recovery after a forced connection loss.

The architecture decision and remaining acceptance requirements are recorded in
[ADR-0036](adr/0036-continuous-voice-and-agent-selection.md).

The settings form has been inspected in light and dark themes. Its provider
test uses the continuous session contract and waits for `session.started`;
browser-owned media no longer waits for the legacy desktop offer broker.
The separate Live profile owns model and voice selection without duplicate
legacy pickers on the provider card.

A synthetic check through the running application's authenticated `/ws/audio`
route now establishes WebRTC, receives `session.started`, completes the real
read-only `describe-app-settings` tool through the gateway and receives spoken
confirmation as non-silent RTP audio. It captures no microphone or screen data.
The transport checks do not replace physical device and acoustic-echo tests.

References: [OpenAI architecture](https://developers.openai.com/api/docs/guides/live),
[delegation](https://developers.openai.com/api/docs/guides/live-delegation),
[migration](https://developers.openai.com/api/docs/guides/live-migration), and
[Gemini tools](https://ai.google.dev/gemini-api/docs/live-api/tools).
