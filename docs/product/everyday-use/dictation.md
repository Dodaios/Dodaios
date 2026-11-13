---
title: "Dictate Into Any App"
slug: dictation
summary: "Turn speech into text in the focused field, recover missed words, and choose what stays local or uses a provider."
section: "Everyday use"
section_order: 2
order: 8
diataxis: howto
status: active
owner: maintainers
last_reviewed: 2026-11-13
phase: "-"
audience: end-user
tags: [dictation, speech-recognition, microphone, shortcuts, privacy, accessibility]
related: [voice-conversations, speech-dictionary, providers-and-api-keys, privacy-and-local-data]
---

Dictation turns speech into text at the cursor in desktop apps and Dodaios. It does not ask the assistant to answer. If insertion is blocked, your
transcript stays on the clipboard and in the history on the **Dictation** tab.

## Before You Start

- Keep the Dodaios desktop app running and allow microphone access.
- In your assistant-named **Voice** section, choose **API Keys** and select a
  ready provider under **Speech to text**.
- Place the cursor in an editable field. Password and protected fields may
  block automatic typing.

## Use Dictation

1. Open the app and field where you want the words to appear, then place the
   cursor at the insertion point.
2. Hold **Push to talk** and speak. Release it when finished. The floating bar
   shows the recording and transcription state. Pause as long as you like: a
   pause never ends the recording.
3. The text appears once, complete, shortly after you stop. No words are shown
   while you speak. A long dictation is read in the background while you are
   still speaking, so the wait after the stop stays short.
4. Check the result at the cursor. If a notice says the text was copied to the
   clipboard, paste it manually into the same field.
5. Open **Voice > Dictation** to review the text and, when it did not simply
   arrive, what became of it.

You can also select the microphone button on the **Dictation** tab. Keep a
target field focused, or return to it before stopping.

### Dictate Into a Chat Box

Select the microphone in a chat box to dictate a message. The button shows a
waveform and a timer while it records, and **Transcribing…** after you stop.
The text is added to what the box already holds.

You can select **Send** while the recording or the transcription still runs.
The message then waits for the dictated text and goes out with it. If the
transcription fails, nothing is sent, the box stays as it is, and a notice
says why.

### Paragraphs and Line Breaks

Say the layout where you want it:

| Say | Result |
|---|---|
| "new paragraph", "next paragraph", "neuer Absatz" | A blank line |
| "new line", "next line", "neue Zeile", "Zeilenumbruch" | A line break |

The Spanish and Portuguese phrases ("nuevo párrafo", "nueva línea", "novo
parágrafo", "nova linha") work the same way. The phrases work in every
dictation language and need no wording model. A phrase you talk about stays
as words: "add a new line to the file" is delivered as that sentence.

A recognizer writes three dots where you pause. Dodaios removes them, so a
pause in the middle of a sentence leaves no mark in the text.

## Choose a Shortcut

Open **Settings > Keyboard shortcuts**. The dictation shortcuts are in the
list with every other shortcut of the app; select the pencil beside one to
record new keys. New combinations save immediately.

| Shortcut | Behavior | Best for |
|---|---|---|
| **Push to talk** | Hold to record; release to finish and insert | Short and precise passages |
| **Hands-free** | Press once to start; press again to stop | Longer passages or accessibility |
| **Paste again** | Re-inserts the latest saved dictation without recording | Recovering from a wrong target |

If Push to talk behaves like a toggle, a notice above the list says so;
select **Switch to hold** there. A combination that is already in use is
refused with the name of the action that holds it.

**Paste again** needs local history. If insertion is blocked, it copies the text
for manual pasting.

## Understand Where the Text Goes

Inside Dodaios, text goes to the focused or last-used editable field,
including a coding terminal. With no target, it remains in history.

For another app, Dodaios places the transcript on the clipboard, sends the
normal paste shortcut, then restores the previous plain-text value. Non-text
clipboard content may not be restorable.

If the system refuses automatic typing, Dodaios leaves the transcript on the
clipboard. History reports **Copied to clipboard** or **Could not insert**.

## Review and Recover Dictations

Each history entry shows the delivered text and its time. When the text was
changed, **What was heard** opens the original recognition. Search checks both
versions. An entry that did not simply arrive says so beside its time, for
example **Copied to clipboard** or **Partly transcribed**.

- **Delete** crosses out an entry but keeps it recoverable.
- **Restore** reactivates a crossed-out entry.
- **Transcribe again** appears on an entry without text and on a partly
  transcribed one, and runs its kept recording with current settings.
- **Delete forever** removes a crossed-out entry and its saved audio.
- **Copy** copies the delivered version.

Transcribe again may produce different words after a provider or language
change. It updates history but does not reinsert text into another app.

## Clean Up or Translate the Text

Open **Voice > Language** and choose the **Spoken language**. Keep **Detect
automatically** unless recognition repeatedly guesses wrong. Wake-word and
assistant reply languages are separate.

**Clean up wording** uses a text model for punctuation, capitalization,
sentence breaks, and self-corrections. The original stays in history. **Test**
uses a fixed sample and saves nothing. If the model fails or changes too much,
Dodaios uses the version from before that pass. The **Provider** row under
**Model** chooses which model does the work.

**Always write in one language** translates and cleans up in one request.
Translation starts off. It runs at the provider you picked, on that provider's
strongest fast model rather than its quickest one, because rewriting a sentence
in another language asks more than punctuating it. If the model times out, text
stays in the spoken language.

A long dictation is given more time than a short one: the budget you set
applies up to about 25 words and then grows with the transcript, up to
`polish_timeout_max_ms`. Waiting longer costs nothing while the provider is
healthy — it only decides what happens when it is not.

> [!warning] A hosted recognition provider receives audio; a hosted wording
> provider receives the transcript. While such an option is on, the Language
> tab says in one sentence which provider your text is sent to.

An on-device recognizer (Parakeet, Whisper or Nemotron) keeps recognition
audio on this computer; the stand-in behind it is on-device too and never
uploads it. Automatic wording also stays local and uses the
unpolished text if no local model answers. Choosing a cloud wording model is an
explicit exception.

## Retention and Deletion

History is local. Defaults keep up to 200 entries for up to 30 days. Successful
dictations do not keep microphone audio.

For partial, failed, empty, or cancelled results, recovery audio is kept only
when enabled. Defaults retain at most 20 recordings for 7 days. **Delete all**
asks once, then irreversibly removes history, recovery audio, and the usage
counts kept with them.

## Operating-System Limits

| System | What can prevent automatic use | What happens instead |
|---|---|---|
| Windows | The target app runs as administrator while Dodaios does not | Text remains on the clipboard |
| macOS | Secure Input, a password field, or missing Accessibility/Input Monitoring access | Text remains on the clipboard; shortcuts may be unavailable |
| Linux X11 | The optional desktop hotkey support is not installed | Use the Dictation button; insertion can still work |
| Linux Wayland | Global shortcuts and cross-app synthetic typing are blocked by design | Use the button and paste from the clipboard |
| Headless host | No desktop microphone or insertion target exists | Dictation reports that it is unavailable |

## Choose What Recognizes Your Speech

Dodaios reads a dictation with the recognizers that exist on your computer:

- A hosted provider reads it while a key for that provider is saved under
  **Voice > API Keys**. A key you save counts from the next dictation on; no
  restart is needed.
- **Parakeet (on this machine)** is the fast on-device recognizer. It reads a
  recording many times faster than real time on an ordinary processor, needs
  no key and no graphics card, and covers 25 European languages including
  German and English. Download it once (about 490 MB) under
  **Voice > API Keys**.
- **Whisper (on this machine)** covers every language. Without a graphics
  card it is slow: a ten-second dictation can take several seconds.

With a hosted provider in front, an on-device recognizer stands in when the
service does not answer in time. Without a saved key, recognition runs on
this computer alone. The **Dictation** tab names the recognizer that answers
the next dictation and says so when it is not the one you configured.

A recording without speech (a muted or wrong microphone, a tap on the key) is
never sent to a recognizer. You get a notice to check the microphone instead
of invented text.

## How It Fits Together

1. A shortcut or the Dictation button starts microphone capture.
2. While you speak, Dodaios finds the speech and the pauses in the recording.
   Silence is cut away and a long recording is cut at your own pauses.
3. Each piece is recognized once. A piece no recognizer could read is counted
   as missing, and the recording is kept so you can transcribe it again.
4. Fixed rules remove pause marks and hesitation sounds, apply spoken
   paragraph and line commands, and repair punctuation. The Speech Dictionary
   corrects known terms.
5. Optional wording or translation produces the delivered version.
6. Dodaios inserts that version or preserves it on the clipboard.
7. Local history records both versions, the outcome, and recovery audio only
   after an incomplete result.

In a [Voice Conversation](voice-conversations), speech becomes a request and
the assistant replies or acts instead.

## Check That It Works

In a plain-text editor, place the cursor after a marker, hold **Push to talk**,
say one sentence, and release. The sentence should appear there and history
should show the sentence with no remark beside its time. An explained
clipboard fallback also confirms that recognition worked.

## Troubleshooting

| What you see | What it usually means | What to do |
|---|---|---|
| **Dictation is not set up on this computer.** | No microphone or ready recognition provider | Check microphone permission, then **Voice > API Keys** |
| The global shortcut does nothing | The binding conflicts, lacks OS permission, or is unsupported on Wayland | Record another shortcut; use the microphone button meanwhile |
| **Copied to clipboard** | The active field rejected synthetic input | Paste manually and check the operating-system table above |
| **Partly transcribed** | No recognizer could read part of the recording | Check the provider, then select **Transcribe again** on the entry |
| Dictation is slow without a key | Whisper runs on the processor | Download **Parakeet** under **Voice > API Keys**, or save a provider key |
| **Nothing was heard** | The recording held no speech | Check the selected microphone and that it is not muted |
| Wording or translation is skipped | No selected model answered safely in time | Run **Voice > Language > Test** or choose another ready provider |

For broader microphone, provider, and desktop checks, read
[Troubleshooting](troubleshooting).

## Next Steps

- Read [Speech Dictionary](speech-dictionary) to correct names and specialist
  words in future dictations.
- Use [Providers and API Keys](providers-and-api-keys) to compare local and
  hosted speech recognition without putting credentials into chat or voice.
- Review [Privacy and Local Data](privacy-and-local-data) for the wider storage
  and deletion model.
- Check [Platform Support](platform-support) before relying on global shortcuts
  or cross-app insertion on a new operating system.
