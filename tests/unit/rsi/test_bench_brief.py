"""The brief domain's check: does a brief point at where the work turned out to be."""

from __future__ import annotations

import pytest

from dodaios.rsi.bench import brief
from dodaios.rsi.bench.model import Domain, Source, Task

MODEL = "dodaios/rsi/bench/model.py"
TEST = "tests/unit/rsi/test_kernel_shapes.py"
DOC = "docs/self-improvement.md"
#: 60 % of the change is in the model, 30 % in its test, 10 % in the doc.
CHANGE = {MODEL: 60, TEST: 30, DOC: 10}


def task(files: dict[str, int] | None = None) -> Task:
    check = {"files": CHANGE if files is None else files}
    return Task("brief-1", Domain.BRIEF, Source.MINED, "acme/app#1", {"request": "r"}, check)


def test_a_brief_that_names_where_most_of_the_work_was_scores_well():
    scored = brief.score(task(), f"Goal: one draw per group. Start in {MODEL}.")

    # Found 0.6 of the change, nothing astray: the balance of 0.6 and 1.0.
    assert scored.score == pytest.approx(0.75)
    assert "found 0.60" in scored.detail and TEST in scored.detail


def test_a_brief_that_names_every_changed_file_scores_one():
    assert brief.score(task(), f"Touch {MODEL}, {TEST} and {DOC}.").score == 1.0


def test_a_brief_that_names_no_file_scores_nothing():
    scored = brief.score(task(), "Make the draw of the splits fair, the way we discussed.")

    assert scored.score == 0.0
    assert scored.detail.startswith("found 0.00") and MODEL in scored.detail


def test_listing_files_the_change_never_touched_costs():
    aimed = brief.score(task(), f"Start in {MODEL}.")
    scattered = brief.score(
        task(),
        f"Look at {MODEL}, dodaios/rsi/overlay.py, dodaios/rsi/storage.py and"
        " dodaios/self_change/gate.py.",
    )

    # Found the same 0.6, but three of four named paths were not touched.
    assert scattered.score == pytest.approx(2 * 0.6 * 0.25 / 0.85, abs=1e-3)
    assert scattered.score < aimed.score
    assert "3 of 4 named paths not touched" in scattered.detail


@pytest.mark.parametrize(
    "text",
    [
        "The pinned draw is in test_kernel_shapes.py.",
        "The pinned draw is in rsi\\test_kernel_shapes.py, see there.",
        "The pinned draw is in unit/rsi/test_kernel_shapes.py.",
    ],
)
def test_a_file_is_named_by_its_name_or_by_a_path_from_further_down(text):
    scored = brief.score(task(), text)

    assert scored.score == pytest.approx(2 * 0.3 / 1.3, abs=1e-3)
    assert "not touched" not in scored.detail


def test_a_python_file_is_named_by_its_module():
    assert brief.score(task(), "Change dodaios.rsi.bench.model.split_of.").score == pytest.approx(
        0.75
    )


def test_a_name_many_folders_have_names_a_file_only_with_its_folder():
    change = {"dodaios/rsi/bench/__init__.py": 50, "dodaios/rsi/gate/__init__.py": 50}

    assert brief.score(task(change), "Export it from __init__.py.").score == 0.0
    assert brief.score(task(change), "Export it from bench/__init__.py.").score == pytest.approx(
        2 * 0.5 / 1.5, abs=1e-3
    )


def test_part_of_a_longer_name_is_not_the_file():
    assert brief.score(task(), "See old_test_kernel_shapes.py and model.pyc.").score == 0.0


def test_an_address_on_the_web_is_not_a_path_of_the_project():
    scored = brief.score(task(), f"Fix {MODEL}; see https://example.com/docs/page.html for why.")

    assert scored.score == pytest.approx(0.75)


def test_a_longer_brief_costs_more():
    short = brief.score(task(), f"Start in {MODEL}.")
    long = brief.score(task(), f"Start in {MODEL}. " + "And mind the details. " * 40)

    assert short.score == long.score
    assert long.tokens > short.tokens == round(len(f"Start in {MODEL}.") / 4)


def test_a_task_without_changed_files_cannot_be_scored():
    with pytest.raises(LookupError):
        brief.score(task({}), "anything")
