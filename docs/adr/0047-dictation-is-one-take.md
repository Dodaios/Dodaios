# ADR-0047 — Dictation is one take: record, recognize once, deliver

**Status:** Accepted · **Date:** 2026-11-13 · **Supersedes:** decisions 3 and 4
of [ADR-0032](0032-final-multilingual-dictation.md)

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
