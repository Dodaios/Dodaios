---
title: "Start Your First Voice Conversation"
slug: start-your-first-voice-conversation
summary: "Start a voice conversation, follow each listening and reply state, and end the call safely on desktop or in the browser."
section: "Start here"
section_order: 1
order: 6
diataxis: tutorial
status: active
owner: maintainers
last_reviewed: 2026-11-24
phase: "-"
audience: end-user
tags: [voice, microphone, wake-word, keyboard-shortcut, realtime, dictation, tutorial]
related: [voice-conversations, audio-and-wake-word, dictation, languages-and-voices]
---

A voice conversation lets you speak naturally, hear the answer, and continue
with follow-up questions. You can begin with your wake phrase, the Call
shortcut, or the idle Dodaios Bar.

The assistant's displayed name comes from your wake phrase. For example,
`Hey Nova` displays `Nova`; without a saved name, the neutral fallback is
`Assistant`. This guide therefore refers to **your assistant**, whatever name
you chose.

This is different from [Dictation](dictation), which inserts spoken words as
text without asking the Brain or speaking a reply.

## Before You Start

- Open the desktop app and wait for **Voice starting…** to become **Ready**.
  A green **Ready – you can speak now** notice confirms that voice finished
  warming up.
- Connect a microphone and speaker or headset, then check both under
  **Settings > Audio devices**.
- On macOS, allow **Microphone** access. The Call shortcut also requires
  Input Monitoring access, which macOS asks for when you save a shortcut. Review
  [Permissions](permissions) if the app reports that access is missing.
- Under **API Keys & Providers > Live calls**, set up one realtime voice
  provider, such as OpenAI GPT-Live, GPT-Live on your ChatGPT subscription,
  Gemini Live, or xAI Grok Live. Every call runs on it.

> [!warning] Never speak a password, API key, recovery code, or other secret.
> Enter credentials only in **API Keys & Providers**.

## Start Your First Conversation

### 1. Confirm that voice is ready

Look below your assistant's name. When **Voice starting…** becomes **Ready**,
voice is available. Wake users should run **Settings > Wake Word > Test wake
word** once to check the phrase, local detector, language, and microphone.

### 2. Start listening

Choose one method:

- **Wake phrase:** Say the saved phrase, wait for **Listening**, then speak.
  Wake detection opens the session; it does not interpret the request.
- **Call shortcut:** Press the configured keys once. Call also works when wake
  activation is off; it is not push-to-talk.
- **Dodaios Bar:** Select the body of the idle bar.

Change **Call (answer / start talking)** and **Hangup** under
**Settings > Voice Keybinds**. On Wayland, use wake or an in-app control if
global shortcuts are unavailable.

Headless installs have no native audio controls. From a browser on localhost
or HTTPS, use **Start Realtime Voice** when offered and allow the microphone.

### 3. Ask a short question

Wait for **Listening**, then ask a short question at normal volume. Activation
feedback is visual; there is no required chime or spoken greeting.

### 4. Follow the conversation states

The default conversation flow is:

**Ready → Listening → Thinking → Speaking → Listening**

| Status | What it means | What to do |
|---|---|---|
| **Ready** | No call is open | Start when you want |
| **Listening** | The microphone is accepting this turn | Speak a request or follow-up |
| **Thinking** | The assistant is answering or acting | Wait for the result |
| **Speaking** | A reply or progress update is playing | Listen, interrupt, or hang up |
| **Error** | The voice path could not continue | End the call and follow the reported fix |

After an answer, the normal setting returns to **Listening** for a follow-up.

## Choose a Realtime Provider

Every call runs on one realtime provider: one live model listens and answers
in the same audio stream. Pick it on its card under **API Keys & Providers >
Live calls**; the status at the top of that tab shows what this call uses.

| Provider | What it needs |
|---|---|
| **OpenAI GPT-Live** | An OpenAI API key |
| **OpenAI GPT-Live (ChatGPT subscription)** | A ChatGPT sign-in (experimental) |
| **Gemini Live** or **Vertex AI Live** | A Gemini or Vertex AI key |
| **xAI Grok Live** | Your xAI API key, the same one the xAI Grok Brain uses; billed per minute on your xAI account |

Wake detection stays local and separate. Some tools remain unavailable in a
live call; [Voice Conversations](voice-conversations) explains how actions are
handed to the regular planner.

If the selected provider cannot open, another ready realtime provider can take
the call. If none is ready, the call ends and says why. Once an action has
started, the call may end instead of replaying it twice.

## Voice Conversation or Dictation?

| Use | Result | Control |
|---|---|---|
| **Voice conversation** | The assistant can answer or act aloud | Wake, Call, or the Dodaios Bar; finish with Hangup |
| **Dictation** | Speech is inserted as text without a reply | Separate Dictation controls |

## End or Cancel the Conversation

Use any one of these controls:

- Say **hang up** or **end the call**.
- Press your configured **Hangup** shortcut.
- Hover over the active Dodaios Bar and select its visible **X** precisely.

Hangup closes the microphone, stops spoken output, and cancels the active turn
or Computer Use action. A longer background agent mission may continue; check
its view if you started one. The sidebar returns to **Ready**.

## How It Fits Together

1. [Audio and Wake Word](audio-and-wake-word) supplies devices and optional
   local activation; Call or the Bar can open the same session.
2. The selected realtime provider handles one live stream, with a startup
   fallback to another ready realtime provider.
3. One language choice controls the answer and voice. A pinned reply language
   wins; **Auto** keeps short interjections in context and can switch after a
   substantive turn. See [Languages and Voices](languages-and-voices).
4. Dictation shares the microphone and uses its own Voice Input provider, but
   stops before the Brain and spoken reply. If voice is unavailable, **Chats**
   remains available.

## Check That It Works

Start one call with your wake phrase, Call shortcut, or the idle Dodaios Bar.
Ask a short question and watch the status move from **Listening** to
**Thinking** or **Speaking**. You should hear the answer and then see
**Listening** again. Use Hangup and confirm that the status returns to
**Ready**.

## Troubleshooting

| What you see | What it usually means | What to do |
|---|---|---|
| **Voice starting…** never becomes **Ready**, or **Error** appears | Voice is warming, or audio/provider setup is unavailable | Wait briefly; review **Audio devices**, **Permissions**, and **API Keys & Providers** |
| The wake phrase does nothing | Wake is off, its local model or language is wrong, or input is quiet | Run **Test wake word** and use Call or the Bar meanwhile |
| The Call shortcut does nothing | The binding is cleared or global shortcuts are blocked | Review **Voice Keybinds**; check macOS permissions or use an in-app control on Wayland |
| **Listening** captures nothing, or **Speaking** is silent | The selected device is wrong, muted, or quiet | Check both selectors and operating-system levels |
| The call ends at once and says no realtime voice provider is ready | No realtime provider has a usable key or sign-in | Set up or test a provider under **API Keys & Providers > Live calls** |
| Browser voice is unavailable | The page is not localhost/HTTPS, or microphone access is blocked | Use a secure address, grant access, and retry |

## Next Steps

- Read [Voice Conversations](voice-conversations) for follow-up turns,
  interruptions, tools, and fallback behavior.
- Read [Audio and Wake Word](audio-and-wake-word) to tune devices and local
  activation.
- Read [Dictation](dictation) when you want speech inserted as text without an
  assistant reply.
- Read [Languages and Voices](languages-and-voices) to choose recognition and
  reply languages or the voice you hear.
