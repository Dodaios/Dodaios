"""A conversation keeps its language through failures, restarts and internal turns.

Forensic 2026-10-19: a person chatting in Turkish in the English UI got error
messages in German, then Spanish, then English, and the answers themselves
switched between Turkish, German and English after an error. Turkish umlauts
scored as German and ç as Portuguese, the misdetected language was pinned as
"Always reply in German", every failure path fell back to its own language
(mostly German), and an internal English "continue" prompt flipped the shared
conversation language to English.
"""
from __future__ import annotations

import pytest

from dodaios.brain.manager import (
    _PROVIDER_DOWN_PHRASES,
    _TURN_HISTORY_OVERRIDE,
    BrainManager,
    _provider_down_phrase,
)
from dodaios.core.protocols import BrainMessage
from dodaios.core.turn_language import (
    conversation_language_from_history,
    detect_conversation_language,
    detect_language_request,
    detect_text_language,
    resolve_conversation_language,
    resolve_output_language,
)

_TURKISH = (
    "Merhaba, bugün hava nasıl?",  # i18n-allow
    "Bana bir e-posta yazar mısın lütfen",  # i18n-allow
    "Neden çalışmıyor bu program",
    "Şunu al ve bana ver",
    "El yazısı ile yaz",
    "Bu dosyayı düzeltebilir misin? Çok önemli.",  # i18n-allow
    "yarın için bir hatırlatıcı kur",
)


def _mgr(reply_language: str = "auto", conv: str = "") -> BrainManager:
    m = BrainManager.__new__(BrainManager)
    m._reply_language = reply_language
    m._conversation_language = conv
    m._turn_detected_lang = ""
    m._provider_down_idx = 0
    return m


@pytest.mark.parametrize("text", _TURKISH)
def test_turkish_is_turkish_not_the_supported_language_it_resembles(text: str) -> None:
    assert detect_text_language(text) == "unknown"
    assert detect_conversation_language(text) == "tr"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Wie wird das Wetter morgen in Istanbul?", "de"),  # i18n-allow
        ("Öffne die Datei", "de"),  # i18n-allow
        ("Ruf bitte Łukasz an", "de"),
        ("What is the weather like tomorrow?", "en"),
        ("¿Qué tiempo hace hoy?", "es"),
        ("Não consigo abrir o ficheiro", "pt"),
    ],
)
def test_supported_languages_are_unchanged(text: str, code: str) -> None:
    assert detect_text_language(text) == code
    assert detect_conversation_language(text) == code


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Bonjour, je voudrais savoir pourquoi ça ne marche pas", "fr"),
        ("سلام، حال شما چطور است؟", "fa"),
        ("Привіт, як справи? Їжак", "uk"),
        ("Привет, как дела?", "ru"),
        ("こんにちは、元気ですか", "ja"),
        ("你好，今天天气怎么样", "zh"),
        ("Hoe gaat het met je vandaag?", "nl"),
        ("Cześć, jak się masz?", "pl"),
    ],
)
def test_other_languages_are_recognised(text: str, code: str) -> None:
    assert detect_conversation_language(text) == code


@pytest.mark.parametrize(
    "text",
    [
        "Sie hat nie angerufen",
        "Hast du mit ihm gesprochen",
        "Mi mamá ama a Pedro",
        "Le dije que no",
        "Eu vi este filme",
        "Ich war most of the time da",
    ],
)
def test_everyday_supported_words_never_read_as_another_language(text: str) -> None:
    assert detect_conversation_language(text) in {"de", "en", "es", "pt", "unknown"}


def test_other_language_word_lists_share_no_word_with_the_supported_ones() -> None:
    from dodaios.core.turn_language import _OTHER_TOKENS, _SETS, _SUPPORTED_COMMON_WORDS

    supported = set().union(*(words for _code, words in _SETS)) | _SUPPORTED_COMMON_WORDS
    for code, words in _OTHER_TOKENS.items():
        assert not words & supported, (code, sorted(words & supported))


def test_a_pinned_stt_tag_never_runs_german_rules_on_turkish() -> None:
    from dodaios.core.turn_language import resolve_transcript_language

    assert resolve_transcript_language("german", "Neden çalışmıyor bu program") == "unknown"


def test_a_continuation_turn_keeps_its_phrase_language() -> None:
    # Inside generate() the turn's resolved language wins over the text, so an
    # internal English prompt never makes a German chat's error phrase English.
    from dodaios.core.turn_language import TURN_LANGUAGE

    m = _mgr(conv="de")
    token = TURN_LANGUAGE.set("de")
    try:
        assert m._phrase_language("Continue the earlier request with the results") == "de"
        assert m._resolve_turn_lang() == "de"
    finally:
        TURN_LANGUAGE.reset(token)
    token = TURN_LANGUAGE.set("tr")
    try:
        assert m._phrase_language("Continue the earlier request with the results") == "en"
        assert "Turkish" in m._reply_language_directive()
    finally:
        TURN_LANGUAGE.reset(token)


def test_system_phrases_for_a_language_without_translations_are_english() -> None:
    for text in _TURKISH:
        assert resolve_output_language("auto", "unknown", text) == "en"
    assert resolve_output_language("auto", None, "tamam", conversation_language="tr") == "en"


def test_turkish_conversation_survives_short_turns_and_stays_turkish() -> None:
    language = ""
    for text in (_TURKISH[0], "tamam", "ok", _TURKISH[2]):
        language = resolve_conversation_language(
            "auto", None, text, conversation_language=language
        )
        assert language == "tr", text


def test_a_short_turn_in_its_own_script_switches_language() -> None:
    assert resolve_conversation_language(
        "auto", None, "Dosyayı aç", conversation_language="en"
    ) == "tr"
    assert resolve_conversation_language("auto", None, "Now", conversation_language="tr") == "tr"


def test_language_requests_name_languages_without_translations() -> None:
    assert detect_language_request("Türkçe konuş") == "tr"  # i18n-allow
    assert detect_language_request("please answer in Turkish") == "tr"
    assert detect_language_request("reply in German") == "de"


def test_history_restores_the_conversation_language_after_a_restart() -> None:
    history = [
        BrainMessage(role="user", content="Merhaba, bugün hava nasıl?"),  # i18n-allow
        BrainMessage(role="assistant", content="Bugün hava güneşli."),  # i18n-allow
        BrainMessage(role="user", content="tamam"),
    ]
    assert conversation_language_from_history(history) == "tr"
    assert conversation_language_from_history([{"role": "user", "content": "ok"}]) == ""


def test_model_is_told_to_answer_in_turkish() -> None:
    m = _mgr()
    m._update_turn_language("Merhaba, bugün hava nasıl?")  # i18n-allow
    assert m.conversation_language == "tr"
    directive = m._reply_language_directive()
    assert "Always reply in Turkish" in directive
    assert "German" not in directive


def test_failure_phrases_in_a_turkish_conversation_are_always_english() -> None:
    m = _mgr()
    for text in _TURKISH:
        m._update_turn_language(text)
        assert m._resolve_turn_lang() == "en", text
        assert m._next_provider_down_phrase() in _PROVIDER_DOWN_PHRASES["en"]
        assert m._action_failed_phrase(text) == m._action_failed_phrase("Do it now please")


def test_an_internal_english_prompt_does_not_change_the_conversation() -> None:
    m = _mgr(conv="tr")
    m._update_turn_language("")  # generate(language_text="") for a continue turn
    assert m.conversation_language == "tr"
    assert m._turn_detected_lang == "tr"


def test_a_chat_turn_takes_its_language_from_its_own_history() -> None:
    # Another chat or a voice turn left English in the shared manager; this
    # chat's own history is Turkish, so a short turn stays Turkish.
    m = _mgr(conv="en")
    token = _TURN_HISTORY_OVERRIDE.set(
        (BrainMessage(role="user", content="Bana bir e-posta yazar mısın lütfen"),)  # i18n-allow
    )
    try:
        m._update_turn_language("tamam")
    finally:
        _TURN_HISTORY_OVERRIDE.reset(token)
    assert m._turn_detected_lang == "tr"
    assert m.conversation_language == "tr"


def test_a_forced_language_without_translations_is_pinned() -> None:
    m = _mgr()
    m._turn_detected_lang = "tr"
    assert "Turkish" in m._reply_language_directive()


@pytest.mark.parametrize("lang", ["auto", "", "tr", "fr", "xx"])
def test_provider_down_phrase_falls_back_to_english(lang: str) -> None:
    assert _provider_down_phrase(lang, 0) == _PROVIDER_DOWN_PHRASES["en"][0]
