"""Dictation mode — speak into whatever text field currently has focus.

One dictation is one take: everything is recorded, each stretch of the
recording is recognized once, and the text is delivered after the stop.

* :mod:`dodaios.dictation.take` — the take itself: record, cut a long
  recording at the speaker's pauses, read each piece once with the first
  recognizer that answers, report what could not be read.
* :mod:`dodaios.dictation.speech_map` — where the speech is in a recording, so
  silence is never sent to a recognizer.
* :mod:`dodaios.dictation.recognizers` — which recognizers exist on this
  computer and in which order they read.
* :mod:`dodaios.dictation.formatting` — the rules between the recognizer's
  text and the delivered text: pause marks out, spoken paragraph and line
  commands in, hesitation sounds out (the lists are in
  :mod:`dodaios.dictation.cleanup`). No model call.
* :mod:`dodaios.dictation.insert` — put text into the focused field of the
  foreground application: clipboard first, paste chord, restore. Reports
  honestly instead of failing silently.
* :mod:`dodaios.dictation.history` — the local record of what was dictated
  (as recognized and as delivered).

On top of those sits the optional second stage:

* :mod:`dodaios.dictation.polish` — a generative wording pass that the rules
  structurally cannot perform. It is gated behind ``[dictation].polish``, it is
  bounded by a hard latency ceiling, and every one of its failure paths returns
  the text unchanged. Its prompt contract, its drift guards and its provider
  surface live in :mod:`~dodaios.dictation.polish_prompt`,
  :mod:`~dodaios.dictation.polish_guards` and
  :mod:`~dodaios.dictation.polish_client`.

The microphone is NOT here: the session that feeds a take lives in
:mod:`dodaios.speech.pipeline` (``start_dictation`` / ``_dictation_session``).
Nothing in this package imports the speech pipeline — the dependency runs one
way only.

Import-cleanliness: nothing here imports a platform-only package at module
scope, so ``import dodaios.dictation`` stays clean on a headless server.
"""

from __future__ import annotations

__all__ = [
    "cleanup",
    "formatting",
    "history",
    "insert",
    "polish",
    "polish_client",
    "polish_guards",
    "polish_prompt",
    "recognizers",
    "speech_map",
    "take",
]
