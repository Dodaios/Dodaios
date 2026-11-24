---
title: "Voice Conversations"
slug: voice-conversations
summary: "Understand how a realtime voice call handles spoken questions, actions, privacy, interruptions, and failures."
section: "Everyday use"
section_order: 2
order: 2
diataxis: explanation
status: active
owner: maintainers
last_reviewed: 2026-11-24
phase: "-"
audience: end-user
tags: [voice, microphone, wake-word, speech-recognition, realtime, language]
related: [audio-and-wake-word, dictation, local-ai-providers, sessions-and-run-inspector]
---

A voice conversation turns speech into a request for your assistant. It can
answer aloud, use a supported tool, or ask before an action that needs your
approval. The normal conversation stays open for follow-up turns until you
hang up or it reaches its quiet-time limit.

This is different from [Dictation](dictation). Dictation delivers your words
as text to the field where you are typing; it does not ask the assistant to
reason, act, or speak a reply.

## Before You Start

- Wait for **Voice starting…** to become **Ready**.
- Choose a working microphone and speaker under **Settings > Audio devices**.
- On macOS, allow **Microphone** access. The Call shortcut also needs
  Input Monitoring access, which macOS asks for when you save a shortcut. Other systems use their own audio
  and shortcut permissions.
- Open **API Keys & Providers > Live calls** and pick one realtime voice
  provider, such as **OpenAI GPT-Live**, GPT-Live on your ChatGPT
  subscription, **Gemini Live**, **Vertex AI Live**, or **xAI Grok Live**.
  Every call runs on the provider you pick there. Without a ready realtime
  provider, a call does not start.

On a headless computer, native wake detection, desktop shortcuts, microphone,
and speaker output are unavailable. A browser can offer **Start Realtime
Voice** when the page is on localhost or HTTPS and microphone permission is
allowed.

> [!warning] Never speak passwords, API keys, recovery codes, or other
> secrets. Enter a required credential only in **API Keys & Providers**.

## How a Voice Conversation Works

A **turn** is one request and its result. A **session** is the call that can
contain several turns.

1. **Start the session.** Say your wake phrase, use the idle voice control, or
   press the configured **Call (answer / start talking)** shortcut. Wake
   detection opens the microphone; it does not answer or transcribe the
   request itself.
2. **Speak while the app shows Listening.** Dodaios waits for a pause long
   enough to mark the end of your request — the **Thinking pause** setting
   says how long; **Automatic** keeps the provider's own turn detection. If
   you keep talking inside that pause, the new words are added to the same
   request instead of being sent as a second one; a clearly finished sentence
   is answered as soon as the pause has passed.
3. **Dodaios prepares one understood request.** The live connection hears
   your audio and sends transcript updates. Your Speech Dictionary corrects
   known names and terms before routing and session history use the text.
4. **Dodaios chooses the path.** An ordinary question can be answered directly.
   A request that needs an app, connected service, Computer Use, or longer work
   goes through the regular planning and Tool Model path. The live voice model
   hands an action request to that path instead of pretending it has every
   tool.
5. **Safety rules check an action.** Low-risk work may continue immediately.
   An ask-level action pauses for a clear yes or no, and a blocked action does
   not run. Review the exact target and effect before saying yes.
6. **Hear the result.** The reply comes back as speech through the open live
   connection. The visible flow
   is usually **Listening → Thinking → Speaking → Listening**.
7. **Continue or hang up.** Conversation mode listens for another turn. An
   optional single-turn setting ends the session after each answer. Silence can
   also end a conversation when an idle limit is enabled.

### Choose a Realtime Provider

Every voice conversation runs on one realtime speech-to-speech provider: one
live model listens and answers within the same audio session. There is no
separate speech-to-text, Brain, and text-to-speech chain for calls.

| Provider | What it needs | Notes |
|---|---|---|
| **OpenAI GPT-Live** | An OpenAI API key | Has its own voice, thinking model, and instructions settings on the same tab |
| **OpenAI GPT-Live (ChatGPT subscription)** | A ChatGPT sign-in | Experimental; uses the subscription's access and limits and never switches to an API key on its own |
| **Gemini Live** | A Gemini API key | |
| **Vertex AI Live** | A Vertex AI key | |
| **xAI Grok Live** | The xAI API key, the same key as the xAI Grok Brain and xAI Text to Speech | Models `grok-voice-latest` (default) and `grok-voice-3.0`; voices such as Eve (default), Ara, Leo, Rex, and Sal; billed per minute on your xAI account |
| **Local voice** | No account | Experimental cards that run the call on this computer or on a local server you set up |

| Question | Answer |
|---|---|
| How do actions work? | Ordinary conversation stays live; supported action requests use the regular planner and Tool Model |
| How does interruption work? | Browser audio uses echo cancellation; desktop interruption is checked locally to avoid reacting to speaker echo |
| What happens on failure? | Another ready realtime provider can take the call, and the app says so because billing may differ. When no realtime provider is ready, the call does not start: it ends and says why |

Pick the provider on its card under **API Keys & Providers > Live calls**. The
call status at the top of that tab says what the current call actually uses.
Changing the provider during an active desktop call reconnects that call with
the new choice; otherwise the change applies to the next call.

### Know What Stays Local

“Local” depends on the realtime provider you pick, not on other voice
settings.

- Desktop wake detection runs locally and only activates the session.
- A hosted realtime provider receives the live conversation audio. The Voice
  Input, Brain, and Read-aloud voice selections do not change that.
- The experimental **Local voice** cards keep the call on this computer or on
  a local server you set up.
- A request handed to the planner and Tool Model uses those models. If they
  are hosted, the request text can leave the device, and the effective provider
  is reported in the session data.

Read [Local AI Providers](local-ai-providers) before treating a mixed setup as
offline.

### Keep One Language Across the Turn

The recognition language controls how speech becomes text. The reply language
controls how the assistant answers. **Voice > Language** belongs to Dictation;
use **Languages** for voice-conversation recognition and reply settings.

Dodaios resolves the reply language once for each turn. A language you pin wins.
In **Auto**, a one- or two-word interjection keeps the conversation's current
language, while a complete request can switch it. When neither speech nor
context gives a clear answer, English is the fallback.

That one decision covers clarification questions, approval prompts, status and
error phrases, the final answer, and the speaking-language choice. A provider
fallback can change the sound of the voice without changing the language rule.
After changing recognition language, end an active call; the next call uses
the new language.

### Interrupt, Cancel, or End the Call

- **Interrupt a reply:** speak clearly over it. Desktop voice waits for
  sustained speech so the assistant's own speaker output is less likely to
  trigger a false interruption. A whisper may not interrupt reliably; use
  **Hangup** when you need an immediate stop.
- **Reject an approval:** answer with a clear no. Changing the subject is not
  a reliable denial; say no or end the call.
- **End the session:** say a clear end-call command, press the configured
  **Hangup** shortcut, or use the active voice control. Hangup stops listening
  and playback and cancels the active assistant or Computer Use turn.
- **Check delegated work:** a background agent mission that already started
  can continue after hangup. Its visible name follows your assistant name, such
  as **Nova-Agent**, with **Assistant-Agent** as the neutral fallback. Review
  its own view and Outputs for the result.

### Give Several Orders in One Call

In a call you do not have to wait for one order to finish before
giving the next. Say "brief the agent in terminal two about the login bug",
and while that is still being sent, "and create an agent for the
documentation":

- Independent actions run side by side. Only work on the screen is done one
  step after another.
- An action that is still running when you move on continues in the
  background. The assistant says that it is running, not that it is done.
- When it finishes, the assistant tells you at the next pause and names the
  order it belongs to. It does not talk over you.
- An order that depends on a running one ("tell that agent to run the tests"
  while the agent is still starting) is carried out when the first one has
  finished.
- Ask "how far are you with the agent?" for the state of the running work.
  A clear stop command cancels all of it; "stop the briefing" cancels one.

Background agent missions run one after another: a second mission is accepted
and starts when the first has ended. A second mission ordered by voice within
half a minute of the first is treated as a repeat of it; wait a moment, or type
the order.

Stopping a call does not undo a tool effect that already completed. If a
realtime connection fails after a request or action has been committed,
Dodaios ends the call instead of replaying the captured audio and risking a
duplicate action. Start a new call for the next turn.

### Understand Session Records

The local session recorder is enabled by default. **Transcription** groups the
recognized user text, recorded replies, spoken notices, and available provider
details by voice session. It does not save the microphone audio for these
views. If a provider supplies no transcript for part of an exchange,
Dodaios cannot reconstruct those missing words later.

**Run Inspector** adds captured routing, tool, timing, approval, and error
details. Dictation uses the separate history on its own tab and can retain
recovery audio only for incomplete results when that option is enabled.

## How It Fits Together

1. [Audio and Wake Word](audio-and-wake-word) supplies the desktop devices and
   optional activation phrase; Call or the in-app control can open the same
   session without wake detection.
2. The selected realtime provider receives the request over one live audio
   connection.
3. The Speech Dictionary corrects recognized terms. The turn's
   recognition and reply language settings keep the conversation consistent.
4. The planner keeps ordinary conversation on the simplest path and sends
   supported actions through the Tool Model, connected tools, permissions, and
   any required safety confirmation.
5. The reply returns as speech. Transcription and Run Inspector record the
   available text and events without controlling the live turn.
6. [Dictation](dictation) uses the same microphone with its own Voice Input
   provider, and its result goes to a text field instead of a spoken reply.

When the selected provider is unavailable, Dodaios uses another ready realtime
provider when it can and names it. When none is ready, the call ends and says
why: no realtime voice provider is ready, check the voice provider under API
Keys. Chats stays usable.

## Check That It Works

1. Start a session with your wake phrase, Call shortcut, or voice control.
2. Ask one harmless question and watch **Listening** change to **Thinking** or
   **Speaking**.
3. Confirm that you hear a relevant answer and the app returns to **Listening**.
4. Use **Hangup**, confirm **Ready**, then open **Transcription** and find the
   completed turn.

During the call, also check the call status at the top of **API Keys &
Providers > Live calls**. It should name the provider the call actually uses.

## Troubleshooting

| What you see | What it usually means | What to do |
|---|---|---|
| Wake or Call does not reach **Listening** | Voice is still warming, the microphone is unavailable, or activation is not ready | Wait for **Ready**, check **Audio devices**, and run **Test wake word**; use an in-app control meanwhile |
| The transcript is empty, wrong, or misses a name | The input device, recognition language, provider, or vocabulary is wrong | Try one short sentence, review **Languages**, and add repeated term mistakes under **Voice > Dictionary** |
| The call ends at once and says no realtime voice provider is ready | The selected provider has no usable key or sign-in, and no other realtime provider is ready | Open **API Keys & Providers > Live calls**, test the selected provider, or set up another one |
| **Speaking** appears but you hear nothing | The output device, volume, or live connection is unavailable | Check the selected speaker and system volume, then test the realtime provider |
| Browser voice is unavailable or cannot hear you | The page is not localhost/HTTPS, microphone access is denied, or the browser lacks required audio support | Use a secure address, allow microphone access, and retry; continue in Chats if audio remains unavailable |

If a call ends after an error, check Transcription and Run Inspector
before repeating an action. The safe recovery may be a new call rather than an
automatic replay.

## Next Steps

- Read [Audio and Wake Word](audio-and-wake-word) to choose devices, activation,
  and the Call and Hangup controls.
- Use [Dictation](dictation) when you want speech inserted into another app
  without an assistant reply.
- Read [Local AI Providers](local-ai-providers) to see which voice parts can
  run on your computer.
- Open [Sessions and Run Inspector](sessions-and-run-inspector) to review saved
  turns, effective providers, actions, and failures.
