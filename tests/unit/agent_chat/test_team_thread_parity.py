"""The team-thread vocabulary is the same in Python, in TypeScript and in every locale (AP-4)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dodaios.agent_chat.team.store import (
    ENTRY_KINDS,
    MODES,
    PHASES,
    ROLES,
    STATES,
    STEP_STATUSES,
)

_SRC = Path(__file__).resolve().parents[3] / "dodaios" / "ui" / "web" / "frontend" / "src"
_API = _SRC / "lib" / "teamThreadsApi.ts"
_LOCALES = sorted((_SRC / "i18n" / "locales").glob("*.json"))


def _ts_list(name: str) -> tuple[str, ...]:
    source = _API.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.DOTALL)
    assert match is not None, name
    return tuple(re.findall(r'"([a-z_]+)"', match.group(1)))


@pytest.mark.parametrize(
    ("name", "python"),
    [
        ("TEAM_THREAD_STATES", STATES),
        ("TEAM_THREAD_PHASES", PHASES),
        ("TEAM_THREAD_ENTRY_KINDS", ENTRY_KINDS),
        ("TEAM_THREAD_MODES", MODES),
        ("TEAM_THREAD_ROLES", ROLES),
        ("TEAM_PLAN_STEP_STATUSES", STEP_STATUSES),
    ],
)
def test_typescript_lists_match_python(name: str, python: tuple[str, ...]) -> None:
    assert _ts_list(name) == python


@pytest.mark.parametrize("locale", _LOCALES, ids=lambda path: path.stem)
def test_every_locale_names_every_state_step_and_reason(locale: Path) -> None:
    texts = json.loads(locale.read_text(encoding="utf-8"))["team_threads"]

    assert set(texts["state"]) == set(STATES)
    # "done" is a state, not a step the header lists.
    assert set(texts["phase"]) == set(PHASES) - {"done"}
    spoken = set(ENTRY_KINDS) - {"user", "notice", "summary"}
    assert set(texts["kind"]) == spoken
    assert set(texts["mode"]) == set(MODES)
    assert set(texts["member_role"]) == set(ROLES)
    assert set(texts["step_status"]) == set(STEP_STATUSES)
    # Every reason and notice the engine can write has words.
    team = Path(__file__).resolve().parents[3] / "dodaios" / "agent_chat" / "team"
    engine = "\n".join(
        (team / name).read_text(encoding="utf-8") for name in ("engine.py", "plan_mode.py")
    )
    reasons = set(re.findall(r'_halt\(\s*team,\s*"\w+",\s*"(\w+)"', engine))
    reasons |= set(re.findall(r'reason="(\w+)"', engine))
    reasons |= {"interrupted", "limit_time", "stalled"}
    assert reasons <= set(texts["reason"]), reasons - set(texts["reason"])
    notices = set(re.findall(r'_notice\(\s*team_id,\s*[^,]+,\s*"(\w+)"', engine))
    notices |= {"plan_agreed", "plan_accepted_by_user"}
    notices |= {"plan_version_agreed", "plan_version_accepted_by_user"}
    notices |= {"step_accepted", "step_accepted_by_user"}
    assert notices <= set(texts["notice"]), notices - set(texts["notice"])
