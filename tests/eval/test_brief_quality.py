"""The brief pipeline held to a fixed set of dictated requests.

A change to the brief rules (a new check, a new lens, another word list) must
not make a good brief come back or let a known kind of bad brief through. Each
case in ``tests/fixtures/brief_quality`` is a request as a person dictates it,
a brief as the lead used to write it and one as it should be written; no model
is asked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dodaios.briefs import BriefDraft, Order, Recipient, gate
from dodaios.briefs.model import SEVERITY_REVISE

CASES = yaml.safe_load(
    (Path(__file__).parents[1] / "fixtures" / "brief_quality" / "cases.yaml").read_text("utf-8")
)


@pytest.fixture
def notes_app(tmp_path: Path) -> Path:
    """The project the cases' briefs are about."""
    root = tmp_path / "notes-app"
    (root / "sync").mkdir(parents=True)
    (root / "ui" / "src").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    (root / "sync" / "client.py").write_text(
        "class UploadError(Exception):\n    pass\n\n\ndef upload(note):\n"
        "    # an upload times out on a slow connection and the note is lost\n"
        "    raise UploadError('timed out after 10s')\n", encoding="utf-8",
    )
    (root / "ui" / "src" / "ReminderRail.tsx").write_text(
        "export function ReminderRail() {\n  // reminder items in the left rail\n"
        "  return null;\n}\n", encoding="utf-8",
    )
    (root / "ui" / "src" / "NotesList.tsx").write_text(
        "export function NotesList() {\n  // the list of notes\n  return null;\n}\n", "utf-8"
    )
    (root / "scripts" / "done_gate.py").write_text("print('DONE')\n", encoding="utf-8")
    (root / "tests" / "test_sync.py").write_text("def test_upload():\n    pass\n", "utf-8")
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "You are done when `python scripts/done_gate.py` says DONE.\n", encoding="utf-8"
    )
    return root


def _order(case: dict, brief: str, folder: Path, session: str) -> Order:
    return Order(
        writer="lead",
        draft=BriefDraft(task=brief.strip()),
        recipient=Recipient(cli="claude", model="claude-fable-5-2", folder=str(folder)),
        person_words=" ".join(str(case["said"]).split()),
        writer_session=session,
    )


def _revise_codes(decision: gate.Decision) -> set[str]:
    return {f.code for f in decision.findings if f.severity == SEVERITY_REVISE}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_kit_tells_the_writer_what_the_request_leaves_open(case, notes_app, briefs_on):
    wanted = case["kit"]
    order = _order(case, "placeholder", notes_app, "kit-" + case["id"])
    kit = gate.kit_module.build(order, with_draft=False)
    assert kit.kind == wanted["kind"]
    assert [lens.key for lens in kit.lenses][: len(wanted.get("lenses", []))] == wanted.get(
        "lenses", []
    )
    assert {phrase.kind for phrase in kit.open_phrases} >= set(wanted.get("leaves_open", []))
    assert {gap.key for gap in kit.gaps} >= set(wanted.get("open_points", []))
    assert kit.facts.checks and kit.facts.checks[0] == "python scripts/done_gate.py"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_old_kind_of_brief_goes_back_with_the_right_findings(case, notes_app, briefs_on):
    decision = gate.review(_order(case, case["weak"], notes_app, "weak-" + case["id"]))
    assert decision.send is False
    assert _revise_codes(decision) >= set(case["weak_finds"]), decision.remarks()


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_a_good_brief_passes_with_nothing_to_revise(case, notes_app, briefs_on):
    decision = gate.review(_order(case, case["strong"], notes_app, "strong-" + case["id"]))
    assert decision.send is True and decision.revised is False
    assert _revise_codes(decision) == set(), decision.remarks()
