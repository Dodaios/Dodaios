---
title: "Speech Dictionary"
slug: speech-dictionary
summary: "Teach speech recognition names and specialist words it often mishears, then test the improvement."
section: "Everyday use"
section_order: 2
order: 6
diataxis: howto
status: active
owner: maintainers
last_reviewed: 2026-11-17
phase: "-"
audience: end-user
tags: [speech-recognition, dictionary, voice, pipeline]
related: [voice-conversations, audio-and-wake-word, languages-and-voices]
---

Use the **Dictionary** for names, brands, abbreviations, and specialist terms
that speech recognition repeatedly spells the wrong way. It is a **Research
Preview**, but its local corrections now reach Pipeline voice, Realtime
transcripts, and Dictation.

The Dictionary changes recognized text. It does not train a provider, improve
microphone audio, detect the wake phrase, or change reply pronunciation.

## Before You Start

1. Open **Voice > Dictionary**.
2. Add the word the way it must be written. In most cases that is all.
3. Never save credentials, recovery codes, or private keys as vocabulary.

Rules are shared across all input languages.

## How a Word Is Found

Speech recognition that does not know a word writes down what it heard, and
it writes it a different way each time. The Dictionary therefore compares the
sound, not the spelling. For a saved word **Dodaios** it corrects all of
these:

| What recognition wrote | Why it counts |
|---|---|
| `dodaios` | The word in the wrong capitalization |
| `Dodayos`, `Doda iOS`, `Dodai-OS` | The same sound, also across a gap or a hyphen |
| `Dodios`, `Diodios`, `du Dios` | Almost the same sound: only vowels differ |
| `Odaios` | The end of the word; the beginning was swallowed |
| `Dodios-Website` | The word inside a hyphenated compound |

An ordinary word is never changed this way. Next to a saved **Notion**, the
word "nation" stays "nation", because it is a real word. Only a spelling that
is no German or English word can be taken for your word.

Two limits follow from this:

- **Short words** (fewer than six sounds, for example a four-letter name) are
  matched by the same sound only. One vowel is the difference between two
  short names.
- **Other languages.** The check for ordinary words knows German and English.
  In a text in another language only the same sound counts.

A name that is not in any word list can sound like one of your words (a
person called "Leiner" next to a saved **Linear**). Save that name too: a
saved word is never rewritten.

## Choose the Right Entry

| What recognition produces | Best entry | Result |
|---|---|---|
| Your word in changing, similar spellings | Add the word | Every spelling that sounds like it becomes the word |
| A different real word ("Grog" for "Grok") | Add the word and fill in **Heard as** | That word is replaced wherever it appears |
| Missing or unrelated text | Fix audio, provider, or language first | A text rule cannot recover words that never appear |

## Add a Name or Term

1. Select **Add**.
2. Enter the intended spelling under **Word** and leave **Heard as** empty.
3. Save and wait about one second.
4. Start a new utterance in the same path and inspect its transcript.

Compatible providers may also receive the term as a recognition hint. The
correction by sound is local and works with every provider.

## Fix a Repeated Misrecognition

1. Select **Add** and enter the intended form under **Word**.
2. Enter the wrong form under **Heard as**.
3. Separate known alternatives with commas, save, wait one second, and retest.

Rules ignore capitalization, tolerate different spaces, and replace only whole
words or phrases. A gap in a variant also matches a hyphen. A variant also
catches other spellings with exactly its sound. Keep variants specific; commas
separate them.

## Understand Where Corrections Apply

| Path | What the Dictionary changes | Important limit |
|---|---|---|
| **Pipeline** | Preview and final transcripts, including fallback | Provider hints load when the provider is built; later edits still correct locally |
| **Realtime** | Transcript, local routing, tools, and hang-up matching | The provider may have begun its own response before local correction |
| **Dictation** | Preview, final text, and insertion into another app | Optional polish or translation happens later; saved terms are protected |

Edits usually affect the next new transcript within one second. Existing
transcripts and Dictation history are unchanged.

Some providers receive a capped list of correct terms when built; variants stay
local. Provider fallback keeps local correction. If the list cannot load,
speech continues with raw text.

## Find, Edit, or Delete Rules

- **Search** matches terms and variants.
- **Edit** changes them; emptying **Heard as** keeps plain vocabulary.
- **Delete** removes an entry immediately, without confirmation or undo.

Correct terms are unique regardless of capitalization. Edit the existing entry
after a duplicate warning. Within an entry, repeated variants merge, spaces are
normalized, and a variant identical to the term is discarded.

One variant can still appear in different entries; avoid this because the
earlier rule can win. Limits are 100 characters per term or variant, 20
variants per entry, and 2,000 entries.

Deletion stops local correction after reload, but does not change history or
retract a hint held by a running provider. Rebuild that provider if needed.

## Privacy and Storage

Entries stay in local app data, survive restarts, and do not sync.

Cloud speech can receive audio and some terms as hints. Dictation polish or
translation can receive terms as protected spellings. Variants stay in the
local corrector. Deletion cannot retract data already sent.

## What Does Not Change

The Dictionary does not fix typed text, history, bad audio, the wrong
microphone, wake detection, reply language, voice, or pronunciation. It cannot
force provider hints. When recognition writes a different real word instead of
yours, it needs that word under **Heard as**.

Use [Audio and Wake Word](audio-and-wake-word) for capture or activation
problems and [Voice Conversations](voice-conversations) for Pipeline and
Realtime behavior.

## How It Fits Together

1. The microphone, language, and active path produce raw text; wake detection
   happens earlier.
2. Explicit replacements run first, then capitalization, then the match by
   sound.
3. Pipeline sends corrected text to the assistant, Realtime uses it locally,
   and Dictation may polish it before insertion.
4. A fallback can change the provider while local rules remain.

## Check That It Works

1. Say one harmless phrase and note the wrong term.
2. Add the intended form and save.
3. Wait one second, then repeat the phrase in the same path.
4. Confirm the Pipeline/Realtime transcript or Dictation draft shows the saved
   form. No app restart should be needed for local correction.

## Troubleshooting

| What you see | Likely cause | What to do |
|---|---|---|
| The next transcript is unchanged | Reload has not happened, or recognition wrote something that does not sound like the word | Wait one second; then add what it wrote under **Heard as** |
| A real word appears instead of yours | An ordinary word is never changed by sound | Fill in **Heard as** with that word |
| A short name stays wrong | Short words are matched by the same sound only | Fill in **Heard as** with the wrong spelling |
| Another person's name turns into your word | The name is in no word list and sounds like your word | Add that name as its own entry |
| Realtime transcript is fixed but its reply is not | The provider interpreted audio before local correction | Retry in Pipeline when corrected text must drive the answer |
| An unrelated phrase changes | A variant is too broad or shared across entries | Make it more specific, remove the duplicate mapping, or delete it |
| Recognition varies every time | Audio, language, or provider behavior is unstable | Check microphone and input language before adding more rules |

## Next Steps

- Read [Dictate Into Any App](dictation) for Dictation delivery, polish, and
  recovery.
- Read [Voice Conversations](voice-conversations) for Pipeline and Realtime.
- Use [Audio and Wake Word](audio-and-wake-word) for microphone and wake issues.
