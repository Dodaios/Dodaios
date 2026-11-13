"""Edits to a node's spec by path (``dodaios/nodes/patch.py``)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from dodaios.nodes.patch import MAX_CHANGES, apply_changes
from dodaios.nodes.types import NodeError


def _deck() -> dict[str, Any]:
    return {
        "title": "Plan",
        "theme": {"dark": False},
        "slides": [
            {"title": "One", "points": ["a", "b"]},
            {"title": "Two", "points": []},
            {"title": "Three", "points": ["c"]},
        ],
    }


def _titles(spec: dict[str, Any]) -> list[str]:
    return [slide["title"] for slide in spec["slides"]]


def _refused(spec: dict[str, Any], changes: Any) -> str:
    with pytest.raises(NodeError) as caught:
        apply_changes(spec, changes)
    return str(caught.value)


# ------------------------------------------------------------------------- set


def test_set_replaces_a_value_and_adds_a_key() -> None:
    out = apply_changes(
        _deck(),
        [
            {"op": "set", "path": "/slides/2/title", "value": "Third"},
            {"op": "set", "path": "/theme/accent", "value": "blue"},
            {"op": "set", "path": "/title", "value": "The plan"},
        ],
    )
    assert _titles(out) == ["One", "Two", "Third"]
    assert out["theme"] == {"dark": False, "accent": "blue"}
    assert out["title"] == "The plan"


def test_set_is_the_default_operation() -> None:
    assert apply_changes(_deck(), [{"path": "/title", "value": "X"}])["title"] == "X"
    assert apply_changes(_deck(), [{"op": " SET ", "path": "/title", "value": "Y"}])["title"] == "Y"


def test_set_on_a_list_replaces_an_item_or_appends_at_the_end() -> None:
    replaced = apply_changes(_deck(), [{"op": "set", "path": "/slides/0/points/1", "value": "B"}])
    assert replaced["slides"][0]["points"] == ["a", "B"]
    at_end = apply_changes(_deck(), [{"op": "set", "path": "/slides/0/points/2", "value": "c"}])
    assert at_end["slides"][0]["points"] == ["a", "b", "c"]
    dash = apply_changes(_deck(), [{"op": "set", "path": "/slides/0/points/-", "value": "z"}])
    assert dash["slides"][0]["points"] == ["a", "b", "z"]


def test_a_negative_index_counts_from_the_end() -> None:
    out = apply_changes(_deck(), [{"op": "set", "path": "/slides/-1/title", "value": "Last"}])
    assert _titles(out) == ["One", "Two", "Last"]


# ---------------------------------------------------------------------- insert


def test_insert_puts_the_value_before_the_index() -> None:
    new = {"title": "New", "points": []}
    first = apply_changes(_deck(), [{"op": "insert", "path": "/slides/0", "value": new}])
    assert _titles(first) == ["New", "One", "Two", "Three"]
    middle = apply_changes(_deck(), [{"op": "insert", "path": "/slides/2", "value": new}])
    assert _titles(middle) == ["One", "Two", "New", "Three"]
    end = apply_changes(_deck(), [{"op": "insert", "path": "/slides/-", "value": new}])
    assert _titles(end) == ["One", "Two", "Three", "New"]
    also_end = apply_changes(_deck(), [{"op": "insert", "path": "/slides/3", "value": new}])
    assert _titles(also_end) == ["One", "Two", "Three", "New"]


# ---------------------------------------------------------------------- remove


def test_remove_takes_a_key_or_a_list_item_away() -> None:
    out = apply_changes(
        _deck(),
        [{"op": "remove", "path": "/theme/dark"}, {"op": "remove", "path": "/slides/1"}],
    )
    assert out["theme"] == {}
    assert _titles(out) == ["One", "Three"]


# ------------------------------------------------------------------------ move


def test_move_puts_a_list_item_at_another_index() -> None:
    forward = apply_changes(_deck(), [{"op": "move", "path": "/slides/0", "to": 2}])
    assert _titles(forward) == ["Two", "Three", "One"]
    back = apply_changes(_deck(), [{"op": "move", "path": "/slides/2", "to": 0}])
    assert _titles(back) == ["Three", "One", "Two"]
    from_text = apply_changes(_deck(), [{"op": "move", "path": "/slides/1", "to": "0"}])
    assert _titles(from_text) == ["Two", "One", "Three"]


# ------------------------------------------------------------- order and paths


def test_changes_apply_in_order() -> None:
    out = apply_changes(
        _deck(),
        [
            {"op": "remove", "path": "/slides/0"},
            {"op": "set", "path": "/slides/0/title", "value": "Was two"},
            {"op": "insert", "path": "/slides/0/points/-", "value": "x"},
        ],
    )
    assert _titles(out) == ["Was two", "Three"]
    assert out["slides"][0]["points"] == ["x"]


def test_a_path_escapes_slash_and_tilde_in_a_key() -> None:
    spec = {"cells": {"a/b": 1, "c~d": 2, "~1": 3}}
    out = apply_changes(
        spec,
        [
            {"op": "set", "path": "/cells/a~1b", "value": 10},
            {"op": "set", "path": "/cells/c~0d", "value": 20},
            {"op": "set", "path": "/cells/~01", "value": 30},
        ],
    )
    assert out["cells"] == {"a/b": 10, "c~d": 20, "~1": 30}


def test_the_input_is_never_changed() -> None:
    spec = _deck()
    before = copy.deepcopy(spec)
    value = {"title": "New", "points": ["p"]}
    changes = [
        {"op": "insert", "path": "/slides/0", "value": value},
        {"op": "remove", "path": "/slides/3"},
        {"op": "move", "path": "/slides/0", "to": 1},
        {"op": "set", "path": "/theme/dark", "value": True},
    ]
    changes_before = copy.deepcopy(changes)
    out = apply_changes(spec, changes)

    assert spec == before
    assert changes == changes_before
    # The result does not share the inserted value with the caller either.
    value["points"].append("later")
    assert out["slides"][1]["points"] == ["p"]


def test_nothing_is_applied_when_a_later_change_fails() -> None:
    spec = _deck()
    before = copy.deepcopy(spec)
    _refused(
        spec,
        [
            {"op": "set", "path": "/title", "value": "Changed"},
            {"op": "remove", "path": "/slides/9"},
        ],
    )
    assert spec == before


# -------------------------------------------------------------- error sentences


@pytest.mark.parametrize("changes", [None, [], {}, "x", ({"path": "/title"},)])
def test_changes_must_be_a_non_empty_list(changes: Any) -> None:
    assert _refused(_deck(), changes) == "'changes' must be a non-empty list of edits."


def test_too_many_changes_are_refused() -> None:
    changes = [{"op": "set", "path": "/title", "value": str(i)} for i in range(MAX_CHANGES + 1)]
    assert _refused(_deck(), changes) == (
        f"At most {MAX_CHANGES} changes at once; send 'spec' for a rewrite."
    )
    assert apply_changes(_deck(), changes[:MAX_CHANGES])["title"] == str(MAX_CHANGES - 1)


def test_a_change_must_be_an_object_with_a_known_op() -> None:
    assert _refused(_deck(), ["/title"]) == (
        'Each change is an object: {"op": ..., "path": ..., "value": ...}.'
    )
    assert _refused(_deck(), [{"op": "swap", "path": "/title"}]) == (
        "A change's 'op' must be one of: set, insert, remove, move, replace, append."
    )


def test_replace_puts_new_text_where_the_passage_stands() -> None:
    spec = {"markdown": "## Plan\n\nWeek one: the till.\n\nWeek two: the grinder."}
    changed = apply_changes(
        spec,
        [{"op": "replace", "path": "/markdown", "find": "the till", "value": "the menu"}],
    )

    assert changed["markdown"] == "## Plan\n\nWeek one: the menu.\n\nWeek two: the grinder."
    assert spec["markdown"].count("the till") == 1


def test_replace_refuses_a_passage_that_is_missing_or_not_unique() -> None:
    spec = {"markdown": "Week one. Week two.", "count": 3}

    missing = _refused(spec, [{"op": "replace", "path": "/markdown", "find": "Month", "value": ""}])
    assert "is not there" in missing and "'get'" in missing
    twice = _refused(spec, [{"op": "replace", "path": "/markdown", "find": "Week", "value": "Day"}])
    assert "occurs 2 times" in twice
    every = apply_changes(
        spec,
        [{"op": "replace", "path": "/markdown", "find": "Week", "value": "Day", "all": True}],
    )
    assert every["markdown"] == "Day one. Day two."
    assert "needs 'find'" in _refused(spec, [{"op": "replace", "path": "/markdown", "value": "x"}])
    assert "needs a text there" in _refused(
        spec, [{"op": "replace", "path": "/count", "find": "3", "value": "4"}]
    )
    assert "nothing there" in _refused(
        spec, [{"op": "replace", "path": "/summary", "find": "a", "value": "b"}]
    )


def test_append_adds_to_the_end_of_a_text_or_a_list() -> None:
    spec = {"markdown": "## One", "slides": [{"title": "a"}], "count": 3}
    changed = apply_changes(
        spec,
        [
            {"op": "append", "path": "/markdown", "value": "\n\n## Two"},
            {"op": "append", "path": "/slides", "value": {"title": "b"}},
        ],
    )

    assert changed["markdown"] == "## One\n\n## Two"
    assert [slide["title"] for slide in changed["slides"]] == ["a", "b"]
    assert "needs a text or a list" in _refused(
        spec, [{"op": "append", "path": "/count", "value": 1}]
    )


@pytest.mark.parametrize("path", ["title", "", None, "slides/0"])
def test_a_path_must_start_with_a_slash(path: Any) -> None:
    message = _refused(_deck(), [{"op": "set", "path": path, "value": 1}])
    assert message.startswith("A change's 'path' must start with '/', e.g. '/slides/0/title'")


def test_the_whole_spec_cannot_be_replaced_by_a_change() -> None:
    assert _refused(_deck(), [{"op": "set", "path": "/", "value": {}}]) == (
        "A change cannot replace the whole spec; send 'spec' instead."
    )


def test_a_path_that_leads_nowhere_names_where_it_stopped() -> None:
    assert _refused(_deck(), [{"op": "set", "path": "/cover/title", "value": 1}]) == (
        "'/cover/title': nothing at '/cover'."
    )
    assert _refused(_deck(), [{"op": "set", "path": "/title/first", "value": 1}]) == (
        "'/title/first': its parent is a single value, not a list or an object."
    )
    deeper = _refused(_deck(), [{"op": "set", "path": "/title/first/x", "value": 1}])
    assert deeper.startswith("'/title/first/x': ")
    assert deeper.endswith(" is a single value, not a list or an object.")


def test_a_path_through_a_single_value_names_that_value() -> None:
    assert _refused(_deck(), [{"op": "set", "path": "/title/first/x", "value": 1}]) == (
        "'/title/first/x': '/title' is a single value, not a list or an object."
    )


def test_a_bad_list_index_says_how_long_the_list_is() -> None:
    assert _refused(_deck(), [{"op": "set", "path": "/slides/first/title", "value": 1}]) == (
        "'/slides/first/title': 'first' is not a list index."
    )
    assert _refused(_deck(), [{"op": "set", "path": "/slides/3/title", "value": 1}]) == (
        "'/slides/3/title': index 3 is outside the list (it has 3 items)."
    )
    assert _refused(_deck(), [{"op": "set", "path": "/slides/4", "value": {}}]) == (
        "'/slides/4': index 4 is outside the list (it has 3 items)."
    )
    assert _refused(_deck(), [{"op": "insert", "path": "/slides/-5", "value": {}}]) == (
        "'/slides/-5': index -5 is outside the list (it has 3 items)."
    )
    assert _refused(_deck(), [{"op": "remove", "path": "/slides/3"}]) == (
        "'/slides/3': index 3 is outside the list (it has 3 items)."
    )
    # "-" means "the end" only where something can be put there.
    assert _refused(_deck(), [{"op": "remove", "path": "/slides/-"}]) == (
        "'/slides/-': '-' is not a list index."
    )


def test_remove_and_list_operations_say_what_is_wrong_with_the_place() -> None:
    assert _refused(_deck(), [{"op": "remove", "path": "/theme/accent"}]) == (
        "'/theme/accent': nothing there to remove."
    )
    assert _refused(_deck(), [{"op": "insert", "path": "/theme/accent", "value": 1}]) == (
        "'/theme/accent': 'insert' needs a list, and this is an object."
    )
    assert _refused(_deck(), [{"op": "move", "path": "/theme/dark", "to": 0}]) == (
        "'/theme/dark': 'move' needs a list, and this is an object."
    )


def test_move_needs_a_target_inside_the_list() -> None:
    assert _refused(_deck(), [{"op": "move", "path": "/slides/0"}]) == (
        "'/slides/0': '' is not a list index."
    )
    assert _refused(_deck(), [{"op": "move", "path": "/slides/0", "to": 3}]) == (
        "'/slides/0': index 3 is outside the list (it has 3 items)."
    )
