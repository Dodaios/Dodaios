"""The parts a brief is made precise with: lenses, open words, done, profiles, effort."""

from __future__ import annotations

from dodaios.briefs import done, effort, gaps, lenses, profiles, terms


def test_lenses_follow_the_nature_of_the_work_and_the_files_in_play():
    picked = lenses.pick("the upload crashes with an error", paths=["sync/client.py"])
    assert [lens.key for lens in picked] == ["defect", "behaviour"]
    said = "die Seitenleiste sieht nicht gut aus"  # i18n-allow
    look = lenses.pick(said, paths=["ui/src/Rail.tsx"])
    assert [lens.key for lens in look] == ["interface"]
    slow = lenses.pick("the list is slow", paths=[])
    assert slow[0].key == "speed"
    assert lenses.pick("hello there") == []


def test_a_python_file_in_a_ui_folder_is_not_the_interface():
    picked = lenses.pick("change the route", paths=["dodaios/ui/web/server.py"])
    assert [lens.key for lens in picked] == ["behaviour"]


def test_open_phrases_in_german_and_english_name_the_missing_fact():
    said = "Die UI sieht einfach nicht gut aus und ist irgendwie langsam"  # i18n-allow
    found = terms.open_phrases(said)
    assert {phrase.kind for phrase in found} == {"look", "slow", "thing"}
    assert all(phrase.name_instead for phrase in found)
    assert terms.open_phrases("Add a retry to upload()") == []


def test_search_words_put_spelled_out_names_first_and_drop_common_words():
    said = 'Bitte fix das `upload_note` in SyncClient, der "Timeout" nervt'  # i18n-allow
    words = terms.search_words(said)
    assert words[:2] == ["upload_note", "SyncClient"]
    assert "Timeout" in words
    assert "Bitte" not in words and "das" not in words


def test_a_quote_is_not_an_open_word_of_the_brief():
    assert terms.vague_left('The person said "it looks bad"; the label is cut off.') == []
    assert "looks bad" in terms.vague_left("The reminder looks bad, clearly improve it.")


def test_the_done_part_is_found_in_the_field_or_in_the_text():
    assert done.done_part("Fix it.", "A test passes.") == "A test passes."
    text = "Fix it.\n\nDone when: the timeout test passes; no note is lost.\n\nBoundaries: none."
    assert done.done_part(text) == "the timeout test passes; no note is lost."
    assert done.done_part("Fix it.") == ""


def test_a_done_that_fits_every_change_is_generic():
    assert done.is_generic("Tests and typecheck pass.")
    assert done.is_generic("All tests green; commit, push and merge with CI green.")
    assert not done.is_generic("A test that simulates a timeout passes.")
    assert not done.is_generic("The logos show in their brand colours in the running app.")


def test_done_points_are_split_and_classified():
    points = done.criteria_of(
        "x",
        "- `python -m pytest tests/sync` is green\n- the fix is merged with CI green\n"
        "- docs/sync.md exists: `docs/sync.md` is in place\n- the dialog shows the retry count",
    )
    assert [p.kind for p in points] == ["command", "landed", "file", "visible"]
    assert points[0].target == "python -m pytest tests/sync"
    assert points[2].target == "docs/sync.md"


def test_the_family_follows_the_model_before_the_cli():
    assert profiles.family_of("claude", "claude-fable-5-2") == "claude_fable"
    assert profiles.family_of("claude", "claude-opus-5-5") == "claude"
    assert profiles.family_of("codex", "") == "codex"
    assert profiles.family_of("agy", "claude-sonnet-5-5") == "claude"
    assert profiles.family_of("agy", "") == "gemini"
    assert profiles.family_of("cursor", "") == "neutral"
    assert profiles.family_of("Claude Code", "") == "claude"


def test_every_profile_names_its_sources_except_the_neutral_one():
    for profile in profiles.PROFILES.values():
        assert profile.writer_notes
        assert profile.sources or profile is profiles.NEUTRAL


def test_effort_follows_the_size_of_the_job_and_never_tops_what_was_named():
    fable = profiles.CLAUDE_FABLE
    hard = effort.choose(fable, "Find the root cause of the flaky upload", kind="investigate")
    assert (hard.level, hard.size, hard.source) == ("high", "hard", "job_size")
    light = effort.choose(fable, "Rename the label to Reminders", kind="implement")
    assert (light.level, light.size) == ("medium", "light")
    named = effort.choose(fable, "Rename the label", named="max")
    assert (named.level, named.source) == ("max", "named")
    off = effort.choose(fable, "Rename the label", enabled=False)
    assert off.level == ""
    assert effort.choose(profiles.NEUTRAL, "Rename the label").level == ""
    for profile in profiles.PROFILES.values():
        for level in (profile.effort_light, profile.effort_usual, profile.effort_hard):
            assert level in ("", "medium", "high")


def test_gaps_name_what_a_request_leaves_open():
    said = "der upload ist kaputt"  # i18n-allow
    found = gaps.find(
        said, kind="implement", lenses=lenses.pick(said), open_phrases=terms.open_phrases(said)
    )
    assert [gap.key for gap in found] == ["expected_behaviour"]
    settled = gaps.find(
        said, kind="implement", lenses=lenses.pick(said),
        open_phrases=terms.open_phrases(said),
        brief="Uploads fail. They should survive a slow connection.",
    )
    assert settled == []
    stated = "der upload ist kaputt, er soll bei langsamer Verbindung nicht abbrechen"  # i18n-allow
    assert gaps.find(
        stated, kind="implement", lenses=lenses.pick(stated),
        open_phrases=terms.open_phrases(stated),
    ) == []
