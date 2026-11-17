# ADR-0047 — Dictation is one take: record, recognize once, deliver

**Status:** Accepted · **Date:** 2026-11-13 · **Supersedes:** decisions 3 and 4
of [ADR-0032](0032-final-multilingual-dictation.md) · **Amended:** 2026-11-17,
decisions 1 and 2 for on-device engines (see the amendment at the end)

## Context

The dictation lane had grown into several recognition passes over the same
audio: a live preview on short segments, a final pass over long overlapping
windows that replaced the preview, incremental formatting of those windows,
and repairs for windows that came back truncated. Each pass was added to fix
what the one before it caused. Measured on a maintainer's Mac on 2026-11-13:

| Signal | Observed |
| --- | --- |
| Wait for a 9 s dictation | 22 to 30 s |
| Recognizer named in the log | `groq-api`, while no key was saved and the local Whisper model answered |
| Local Whisper `large-v3-turbo` on the processor | 5.9 s for 10.5 s of speech, 14.6 s for 46.6 s |
| A deadline meant for a cloud call | cut the only working recognizer off after "18 s for 8.9 s of audio" |
| A key saved in the settings | unused by dictation until the app was restarted |
| Text in a chat box | sent without the dictated words after an 8 s wait |

People also reported three dots in the text wherever they paused, and spoken
paragraph commands that worked only when a wording model happened to answer.

## Decision

1. **One take.** A dictation records everything and each stretch of the
   recording is recognized exactly once (`dodaios/dictation/take.py`). There
   is no live preview and no second pass. No text exists before the stop.
2. **Cut at pauses, read while speaking.** A recording up to about 30 s is
   one request. A longer one is cut at the speaker's own pauses, and each
   piece is read in the background while the person still speaks. After the
   stop only the last piece is left, so the wait does not grow with the
   length. Pieces are never overlapped and never re-read.
3. **Silence is never sent.** The recording is mapped for speech while it
   arrives (`dodaios/dictation/speech_map.py`, the bundled Silero model, a
   loudness detector as the floor). A recording without speech asks no
   recognizer. Silence around the words is cut off and a pause longer than
   1.2 s is shortened to 0.5 s.
4. **Recognizers are what really runs** (`dodaios/dictation/recognizers.py`).
   A cloud provider is on the list only while a key is saved, an on-device
   engine only while its runtime and model are installed, each under its own
   name. The list is resolved again when a key is saved or removed. One
   recognizer leads and one stands in; a recognizer that fails is set aside
   for the rest of the take. A person who chose an on-device recognizer gets
   on-device recognizers only.
5. **A fast on-device recognizer.** Parakeet TDT 0.6B v3 through sherpa-onnx
   is a provider of its own (`parakeet-local`). On a processor without a
   graphics card it leads the on-device engines where it is downloaded and
   covers the language. The out-of-process local Whisper engine stays for
   graphics cards and for the languages Parakeet does not cover.
6. **Formatting is rules** (`dodaios/dictation/formatting.py`). Pause marks
   are removed, spoken paragraph and line commands become layout, hesitation
   sounds go, punctuation is repaired. No model call. The optional wording
   pass runs after these rules on the whole text.
7. **A chosen language is told to the recognizer.** `auto` detects; a clip too
   short to detect from is told the language recent dictations were in.
8. **A chat box waits for its text.** The composer shows a transcribing state
   after the stop, and a Send pressed meanwhile goes out when the text has
   arrived. A failed dictation sends nothing.

## Measured

Same Mac (Apple M4, 16 GB, no key saved), synthetic German speech:

| Recognizer | 10.5 s of speech | 46.6 s of speech |
| --- | --- | --- |
| Local Whisper `large-v3-turbo`, processor | 5.9 s | 14.6 s |
| Parakeet v3 int8, processor, 4 threads | 0.29 s | 1.2 to 1.5 s |

With the 46.6 s recording fed as a live take, the first 30 s were read while
the rest arrived and the text was ready 0.5 s after the stop.

## Consequences

- The settings `partial_interval_s`, `segment_seconds`, `final_quality_pass`,
  `final_window_seconds`, `final_overlap_seconds` and `code_switching` are
  gone. A configuration file that still holds them loads unchanged.
- A language pin now reaches the recognizer. Somebody who mixes languages in
  one dictation uses `auto`.
- Two pieces of one recording are recognized apart. A cut that falls inside a
  sentence shows as a sentence break there; the cut waits for a pause of
  0.9 s before it settles for a shorter one to make that rare.
- Parakeet covers 25 European languages. Speech in another language is read
  by Whisper or a cloud provider.
- The voice lane still builds its recognizer once at start. A key saved for
  it counts after a restart, as before; only dictation resolves per press.

## Rejected

- **Live text while speaking.** It needs a second recognition of the same
  audio, shows words that change, and is what the removed passes existed for.
- **One request for the whole recording, whatever its length.** The wait
  after the stop then grows with the recording, a slow connection uploads
  minutes of audio at the end, and one failure loses all of it.
- **Whisper on the Mac's graphics chip.** The backend is marked experimental
  by its runtime, and it measured three times slower than Parakeet.

## Amendment 2026-11-17: an on-device engine reads while the person speaks

### Context

The wait after the stop still grew with the dictation. From the history of
150 dictations on a maintainer's Windows machine (local Whisper
`large-v3-turbo` on a graphics card, hold-to-talk):

| Speech in the dictation | Median wait after the stop |
| --- | --- |
| under 5 s | 0.28 s |
| 5 to 15 s | 0.48 s |
| 15 to 30 s | 0.90 s |
| 30 to 60 s | 1.6 s |
| over 60 s | 4.6 s |

Four causes, each measured:

- **The recording was read after the stop.** A piece was cut only from 30 s
  of speech on, at a pause of 0.9 s. This speaker pauses that long about
  three times a minute and often not at all, so most dictations were one
  request made when the key came up. A reading costs about 0.16 s plus 2 %
  of the clip's length.
- **The language was found out on every reading.** With `auto`, the engine
  passes the audio through its encoder a second time: 0.09 s per reading.
- **The recognizer waited its turn behind other work.** With every processor
  thread busy (builds, tests, several coding agents), the same 3 s clip took
  0.23 to 0.32 s at normal process priority and 0.185 s one class above,
  every time.
- **A short clip counted as a busy graphics card.** A clip of 1.3 s that took
  0.27 s crossed the "busy card" line and sent the next minute of dictations
  to the cloud provider.

### Decision

1. **An on-device engine reads the open piece while the person speaks.** A
   reading starts when the voice has stopped for 0.15 s, at the next gap
   between two words once 5 s of speech are new, and without a gap once 10 s
   are. One reading runs at a time.
2. **What a reading settles is kept.** A recognizer marks breaks in its text
   with times. The text up to such a break stays as read when the part holds
   at least 12 s of speech and the reading heard speech behind the break
   (0.5 s behind the end of a sentence, 2 s behind a break inside one). The
   cut is placed in the nearest gap in the speech, or at the quietest moment
   near the break when the speaker ran two sentences together, never on the
   recognizer's time alone. The end of a sentence is preferred. The next
   piece begins at the cut. What lies behind the cut is read again with what
   follows.
3. **After the stop only the rest is read.** A reading the speaker added
   nothing to is the text, and no call follows the stop. A short last word
   after a kept part is read together with that part, never alone and never
   dropped.
4. **A paid service is asked once.** It is never sent audio whose reading may
   be thrown away. Decisions 1 and 2 of this record stay as they were for a
   cloud provider.
5. **A full stop before words that carry on in lower case becomes a comma.**
   The recognizer ended one piece with a full stop and wrote the next as the
   rest of the sentence: the speaker only took a breath there.
6. **The language of a take is found out once.** A reading of at least 6 s
   whose engine is sure of the language (0.8) decides it for the rest of the
   take.
7. **The recognizer process runs one priority class above normal on
   Windows**, set after its model has loaded. Never "high".
8. **A clip under 4 s says nothing about the card.**
9. **An engine that is too slow is not read ahead with.** A reading that took
   longer than 1 s plus 12 % of its clip turns reading ahead off for that
   engine. Every dictation's last reading measures it again.
10. **A failed reading ahead costs nothing.** It is no error, and it does not
    make another recognizer the first choice.
11. **A paste waits up to 0.4 s for a modifier key on its way up.** The text
    can now be ready before the last finger has left the key that ended a
    hold dictation.

No text is shown before the stop. That part of decision 1 holds.

### Measured

14 kept recordings of real dictations, 36 shorter takes cut from them at the
speaker's own pauses (key released 0.16 s after the last sound) and 24 with
the key released 0.6 s into the words that follow a pause, the worst moment
for a reading that just started: 74 in all. Each ran as a live take on a clock that
advances with the audio. Every reading was decoded by the real engine and
took the time measured for a clip of its length on that machine, so the
result does not depend on what else the machine was doing.

| Wait after the stop | Before | After |
| --- | --- | --- |
| Median | 0.51 s | 0.25 s |
| Mean | 0.60 s | 0.25 s |
| Longest | 1.49 s | 0.87 s |
| Under 5 s of speech, median | 0.19 s | 0.09 s |
| 5 to 15 s | 0.44 s | 0.25 s |
| 15 to 30 s | 0.64 s | 0.24 s |
| 30 to 60 s | 1.01 s | 0.36 s |
| Over 60 s | 1.07 s | 0.47 s |
| Key released 0.26 s after the last word instead of 0.16 s, median | 0.51 s | 0.18 s |
| Every reading three times as slow, mean | 1.82 s | 0.92 s |
| Dictations slower than before | | 0 of 74 |

The same recordings in real time, old and new take side by side, each with
its own engine process, the old one at normal priority:

| Wait after the stop, 30 of the recordings | Before | After |
| --- | --- | --- |
| Median | 0.50 s | 0.18 s |
| Mean | 0.54 s | 0.17 s |
| Longest | 1.64 s | 0.49 s |
| Under 5 s of speech, median | 0.16 s | 0.06 s |
| 5 to 15 s | 0.40 s | 0.20 s |
| 15 to 30 s | 0.55 s | 0.17 s |
| 30 to 60 s | 1.51 s | 0.27 s |
| Over 60 s | 0.92 s | 0.43 s |
| Dictations slower than before | | 0 of 30 |
| Words that differ from the `large-v3` reading | 11.7 % | 11.8 % |

Words that differ from a one-shot reading by the larger `large-v3` model, on
the same 74 recordings: 13.6 % before, 13.7 % after.

### Consequences

- An on-device engine decodes about three times the audio of a dictation
  while it runs. On a graphics card that is a few seconds of work per minute
  of speech. It costs nothing but that.
- "Each stretch is recognized exactly once" no longer holds for an on-device
  engine. It holds for a cloud provider.
- A cut can fall inside a sentence when the speaker ended none for a while.
  The text before the cut was read with the words behind it in the clip; the
  piece behind it starts without the words before.

### Rejected

- **Cutting a cloud provider's recording earlier, at pauses alone.** Faster,
  and 15.1 % of the words differed from the reference instead of 13.6 %.
- **Telling the recognizer the words before a piece.** 14.1 % instead of
  13.5 %.
- **Keeping parts of 5 or 8 s.** A few milliseconds faster, and the full
  recordings read worse.
- **The engine at full precision (`float16`) instead of `int8_float16`.**
  Measured side by side: no faster up to 6 s of audio, 6 % faster at 30 s,
  for 1 GB more card memory.
- **A shorter pause before the paste.** It could not be verified without
  taking the keyboard focus on a machine in use. `[dictation].paste_delay_ms`
  stays at 120.

