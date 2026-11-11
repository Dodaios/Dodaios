"""``find_tools`` finds the right tool from a German or English request."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from dodaios.brain.tool_search import rank_tools


@dataclass
class _T:
    description: str
    search_aliases: tuple[str, ...] = ()


_CORPUS = {
    "agentmail/send_message": _T("[MCP: agentmail] Send an email message from an inbox."),
    "agentmail/list_threads": _T("[MCP: agentmail] List email threads in an inbox."),
    "agentmail/get_message": _T("[MCP: agentmail] Read one email message by id."),
    "google_calendar/list_events": _T("List calendar events in a time range, e.g. tomorrow."),
    "google_calendar/create_event": _T("Create a calendar event with attendees and a time."),
    "linear/save_issue": _T("[MCP: linear] Create or update an issue (ticket) in a team."),
    "linear/list_issues": _T("[MCP: linear] List issues (tickets) filtered by assignee or state."),
    "linear/list_projects": _T("[MCP: linear] List projects of the workspace."),
    "github/create_pull_request": _T("[MCP: github] Open a pull request on a repository."),
    "github/list_issues": _T("[MCP: github] List issues of a repository."),
    "supabase/execute_sql": _T("[MCP: supabase] Run a SQL statement against the database."),
    "list_missions": _T("List the missions that are active right now, with their progress."),
    "spotify": _T("Play music, pause, skip and queue songs on Spotify."),
    "home_assistant": _T("Switch lights and devices of the smart home."),
    "weather_report": _T("Current weather and forecast for a place.", ("wetter",)),
}


def _top3(query: str) -> list[str]:
    return rank_tools(query, _CORPUS)[:3]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("schick eine Mail an", "agentmail/send_message"),
        ("send an email to Anna", "agentmail/send_message"),
        ("what's running", "list_missions"),
        ("was läuft gerade", "list_missions"),
        ("Kalender morgen", "google_calendar/list_events"),
        ("what is on my calendar tomorrow", "google_calendar/list_events"),
        ("linear ticket", "linear/save_issue"),
        ("neues Ticket in Linear anlegen", "linear/save_issue"),
        ("Pull Request öffnen", "github/create_pull_request"),
        ("SQL gegen die Datenbank", "supabase/execute_sql"),
        ("spiel Musik", "spotify"),
        ("Wetter in Berlin", "weather_report"),
    ],
)
def test_realistic_requests_find_the_tool_in_the_top_three(query: str, expected: str) -> None:
    assert expected in _top3(query), (query, rank_tools(query, _CORPUS)[:5])


def test_a_name_hit_beats_the_same_word_in_a_description() -> None:
    ranked = rank_tools("projects", _CORPUS)
    assert ranked[0] == "linear/list_projects"


def test_no_match_returns_nothing() -> None:
    assert rank_tools("zzzz qqqq", _CORPUS) == []


def test_ranking_is_deterministic() -> None:
    flipped = dict(reversed(list(_CORPUS.items())))
    assert rank_tools("issue", _CORPUS) == rank_tools("issue", flipped)
