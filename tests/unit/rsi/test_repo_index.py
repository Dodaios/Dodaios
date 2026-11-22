"""The compact repository index: what is in play, in which order, within its budget."""

from __future__ import annotations

from dodaios.rsi import repo_index
from dodaios.rsi.repo_index import RepoState


def test_nothing_in_play_is_nothing_to_send():
    assert repo_index.render([RepoState("notes"), RepoState("web", prs=2)], total=2, rev=1) == ""


def test_one_line_per_repository_in_play_and_a_count_for_the_rest():
    states = [
        RepoState("notes", busy=3, waits=1, prs=2, prs_failing=1, dirty=True),
        RepoState("shop-web", waits=2, prs=1),
        RepoState("billing-api", busy=2, prs=1, prs_running=1, conflict=True),
        RepoState("infra", prs=2, gate_stuck=True),
        RepoState("quiet-one"),
    ]
    text = repo_index.render(states, total=23, rev=41)
    assert text.splitlines() == [
        "[Repos, rev 41: 4 of 23 in play. Detail: workspace-orchestrate status "
        "project=<name>; pull-requests-list.]",
        "infra: idle; PR 2 passing; gate stuck",
        "notes: 3 busy, 1 waits for you; PR 2, 1 failing; main dirty",
        "shop-web: 2 wait for you; PR 1 passing",
        "billing-api: 2 busy; PR 1 running; conflict",
        "Quiet: 19 repos.",
    ]


def test_the_order_is_waiting_then_busy_then_named_then_recent_then_red():
    states = [
        RepoState("e-red", prs=1, prs_failing=1),
        RepoState("d-recent", recent=True),
        RepoState("c-named", named=True),
        RepoState("b-busy", busy=1),
        RepoState("a-waits", waits=1),
        RepoState("z-waits", waits=1),
    ]
    assert [s.name for s in repo_index.in_play(states)] == [
        "a-waits", "z-waits", "b-busy", "c-named", "d-recent", "e-red",
    ]
    assert [repo_index.tier(s) for s in repo_index.in_play(states)] == [1, 1, 2, 3, 4, 5]


def test_two_renders_without_a_change_are_the_same_bytes():
    states = [RepoState("notes", busy=1), RepoState("web", waits=1)]
    first = repo_index.render(states, total=5, rev=7)
    again = repo_index.render(list(reversed(states)), total=5, rev=7)
    assert first == again
    assert repo_index.body_digest(states, total=5) == repo_index.body_digest(
        list(reversed(states)), total=5
    )


def test_the_digest_moves_only_when_what_is_said_moves():
    base = [RepoState("notes", busy=1)]
    same = repo_index.body_digest(base, total=5)
    assert repo_index.body_digest([RepoState("notes", busy=2)], total=5) != same
    assert repo_index.body_digest(base, total=6) != same
    # A fact the index does not print changes nothing.
    assert repo_index.body_digest([RepoState("notes", busy=1, prs=0)], total=5) == same


def test_forty_repositories_in_play_stay_within_the_budget():
    states = [
        RepoState(f"service-number-{i:02d}", busy=2, prs=3, prs_failing=1) for i in range(40)
    ]
    text = repo_index.render(states, total=60, rev=3)
    assert len(text) <= repo_index.BUDGET_CHARS
    lines = text.splitlines()
    assert lines[0].startswith("[Repos, rev 3: 40 of 60 in play.")
    assert lines[-1] == "Quiet: 20 repos."
    assert lines[-2].startswith("More in play: service-number-")
    assert lines[-2].endswith(tuple(f"+{n}" for n in range(1, 40)))


def test_a_repository_that_waits_for_the_person_is_never_dropped():
    busy = [RepoState(f"busy-repository-with-a-long-name-{i:02d}", busy=9) for i in range(40)]
    waiting = [
        RepoState(f"waits-{i}", waits=1, prs=4, prs_failing=2, dirty=True) for i in range(12)
    ]
    text = repo_index.render([*busy, *waiting], total=52, rev=1, budget=600)
    assert len(text) <= 600
    for state in waiting:
        assert f"{state.name}: " in text


def test_a_single_quiet_repository_is_counted_in_the_singular():
    text = repo_index.render([RepoState("notes", busy=1), RepoState("other")], total=2, rev=1)
    assert text.endswith("Quiet: 1 repo.")


def test_no_fact_that_changes_by_itself_is_printed():
    text = repo_index.render(
        [RepoState("notes", busy=1, prs=1, prs_running=1, recent=True)], total=1, rev=2
    )
    assert text.splitlines()[1] == "notes: 1 busy; PR 1 running"
