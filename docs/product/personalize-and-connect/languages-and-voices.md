---
title: "Languages and Voices"
slug: languages-and-voices
summary: Choose reply language, speech language, and speaking voice while keeping every layer of a conversation consistent.
section: "Personalize and connect"
section_order: 3
order: 3
diataxis: howto
status: active
owner: maintainers
last_reviewed: 2026-11-24
phase: "-"
audience: end-user
tags: [languages, voice, speech, settings]
related: [voice-conversations, providers-and-api-keys, audio-and-wake-word]
---

The interface, replies, speech recognition, dictation, and speaking voice are
separate choices.

## Before You Start

Voice conversations need a microphone and a ready realtime voice provider.
Enter credentials only in **API Keys & Providers**, never in chat or speech.

## Understand the Language Settings

| Choice | Where it lives | What it changes |
|---|---|---|
| **Interface Language** | **Settings → Languages** | Labels, buttons, and other app text |
| **Voice Recognition Language** | **Settings → Languages** | How normal spoken assistant turns are transcribed |
| **Reply Language** | **Settings → Languages** | Answers, acknowledgements, status messages, action readbacks, and spoken output |
| **Dictation Language** | **Voice → Language** | Speech inserted into another app or the assistant's text box |
| **Translation target** | **Voice → Language** | The fixed language in which translated dictation is delivered |
| **Call voice** | **API Keys & Providers > Live calls**, on the realtime provider card | The sound of a call, not its words |
| **Read-aloud voice** | **API Keys & Providers > Live calls > Read-aloud voice** | The voice that reads answers aloud and speaks notices outside calls |

Interface Language supports English, German, Spanish, Simplified Chinese, and
European Portuguese. The first-run setup window offers the same five choices in
its top corner. Reply Language supports English, German, Spanish, and European
Portuguese equally.
Recognition and Dictation offer Automatic plus a much wider language list. A
provider may support fewer languages than the app lists.

Wake-word pronunciation has its own setting and need not match these choices.
See [Audio Devices and Wake Word](audio-and-wake-word).

## Choose Interface and Reply Language

1. Open **Settings → Languages**.
2. Choose an **Interface Language**. The open app changes immediately.
3. Under **Reply Language**, choose **Automatic** or pin English, German,
   Spanish, or European Portuguese.

A reply pin wins for every new turn and keeps acknowledgements, errors, action
readbacks, and speech aligned with the answer.

In **Automatic**, a one- or two-word interjection keeps the established
conversation language. A complete turn can switch to another supported reply
language. Ambiguous speech can use the recognition tag; with no usable signal
or history, the fallback is English.

Names, commands, and code terms may keep their original form.

## Choose Recognition and Dictation Language

For normal voice conversations, start **Voice Recognition Language** on
**Automatic**. Pin one language only after repeated wrong detection.

Dictation is independent. Open **Voice → Language** and choose its language:

- Keep **Automatic** when you use multiple languages.
- Pin one language only when detection repeatedly fails; other languages can
  become less accurate.
- Use **Improve wording** to let a small text model repair punctuation and
  wording. **Automatic provider** uses an available family; a pin uses only
  that family.
- Turn on **Translate dictation** to deliver every dictation in one selected
  target language. It is off by default and shares the wording model call.

Wording and translation may send text to their provider. If no provider
answers, it times out, or the result changes too much, the raw transcript is
delivered and remains visible in history. With local recognition, Automatic
wording avoids silently choosing cloud processing; selecting a cloud family
opts in. A local provider such as Ollama can keep the pass on-device.

If source and target are pinned to the same language, nothing is translated.
Read [Dictate Into Any App](dictation) for history and recovery.

## Choose the Call Voice and the Read-Aloud Voice

Open **API Keys & Providers > Live calls**. There are two kinds of voice:

| Voice | Where you pick it | Where you hear it |
|---|---|---|
| **Call voice** | On the realtime provider card you use for calls, such as GPT-Live, Gemini Live, or xAI Grok Live | Every voice conversation |
| **Read-aloud voice** | Under **Read-aloud voice**, at the bottom of the tab | Answers read aloud and spoken notices outside a call |

For a call, choose a model and voice on the realtime provider card. Catalogs
are provider-specific. **xAI Grok Live**, for example, offers the models
`grok-voice-latest` (default) and `grok-voice-3.0` and voices such as Eve
(default), Ara, Leo, Rex, and Sal. **Provider default** clears an explicit
voice pin and cannot be previewed. If the call moves to another realtime
provider, the exact sound can change.

For read-aloud, activate a text-to-speech provider and use its model or voice
list. Where **Preview voice** is offered, listening does not save the voice.

### Use Local Piper Voices

**Piper (on this machine)** is a keyless read-aloud voice. Its in-app install
downloads about 270 MB: one voice each for English, German, Spanish, and
European Portuguese. Piper selects the voice matching each reply; text and
speech stay on-device.

Piper runs on CPU, may sound less natural than cloud speech, and is not a call
voice. A missing language voice can cause the wrong accent; complete the
provider-card download. See [Use Local AI Providers](local-ai-providers).

## Know When Changes Apply

| Change | When it applies |
|---|---|
| Interface language | Immediately in every open client |
| Reply language | On new turns; an active call reconnects |
| Recognition language | End and start the current call |
| Dictation language, wording, or translation | The next dictation; no app restart |
| Read-aloud provider, model, or voice | The next spoken output when live switching succeeds; otherwise after an app restart |
| Realtime provider, model, or voice | The active call reconnects; otherwise the next call |

A running turn may finish with its old setting. Restart only when live switching
did not apply; a restart interrupts live terminal panes before they reattach.

## How It Fits Together

1. Recognition creates a transcript; Dictation has its own setting.
2. The reply resolver applies a pin or follows the conversation language.
3. The realtime provider speaks the call in that language; the read-aloud
   voice uses it outside calls.
4. Voice selection changes sound, never reply policy.

## Check That It Works

1. Set the interface to English and pin replies to Spanish.
2. Ask in English. Labels should stay English while answer and speech are
   Spanish.
3. Return replies to **Automatic**, dictate a test, and inspect its history.

## Troubleshooting

| What you see | What to do |
|---|---|
| The interface changed but replies did not | Change **Reply Language**, not Interface Language |
| Speech is transcribed in the wrong language | Pin **Voice Recognition Language**, then start a new call |
| Dictation is wrong while voice chat is correct | Change **Voice → Language**; it is independent of normal recognition |
| Translation returns the spoken language | Check that translation is on, the target differs from a pinned source, and the wording provider test succeeds; failures return raw text |
| A short turn does not change reply language | Use a complete sentence or temporarily pin Reply Language |
| A voice is missing | Open the active provider card; catalogs do not transfer between providers |
| Piper is silent or has the wrong accent | Complete its local voice download and confirm Piper is the active **Read-aloud voice** |
| A call reconnects | A language, provider, model, or voice setting changed at session level; test the next turn |

## Next Steps

- Read [Voice Conversations](voice-conversations) for realtime providers and calls.
- Read [Dictate Into Any App](dictation) for shortcuts, delivery, and history.
- Read [Use Local AI Providers](local-ai-providers) for offline speech options.
- Read [Providers and API Keys](providers-and-api-keys) for setup and fallback.
