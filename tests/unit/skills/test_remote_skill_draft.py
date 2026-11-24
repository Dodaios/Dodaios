"""A SKILL.md from the skill catalog or the marketplace lands as a draft.

A skill is text the assistant follows, and its frontmatter can ask for more:
a trigger, a schedule, a state of its own. A downloaded file is third-party
text nobody here has read yet, so it is stored switched off, it is installed
under the name it is listed with and no other, it never replaces a file that
is already there, and the stamp that switches it off is read back by the same
rule the loader uses.

Every download here is answered by a local mock transport; nothing reaches the
network.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from dodaios.skills import finder as finder_mod
from dodaios.skills.cron_routines import desired_schedules
from dodaios.skills.finder import SkillCandidate, SkillFinder
from dodaios.skills.loader import parse_skill
from dodaios.skills.registry import _rewrite_state_in_frontmatter
from dodaios.skills.schema import SkillLifecycleState

_SCHEDULED = 'triggers:\n  - type: schedule\n    cron: "*/5 * * * *"\n'


def _skill_md(name: str, *, extra: str = "") -> str:
    return (
        "---\n"
        'schema_version: "1"\n'
        f"name: {name}\n"
        "description: Plain test skill.\n"
        f"{extra}"
        "---\n\n"
        "# Body\n\nDo the thing.\n"
    )


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(finder_mod, "user_skills_dir", lambda: root)
    return root


def _serve(monkeypatch: pytest.MonkeyPatch, body: str | bytes) -> None:
    """Answer every download of the finder with ``body``, from a mock transport."""
    payload = body.encode("utf-8") if isinstance(body, str) else body
    real = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    def client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)


def _candidate(name: str) -> SkillCandidate:
    return SkillCandidate(
        name=name,
        title=name,
        description="",
        source="catalog",
        source_url="https://example.invalid/skills",
        raw_url=f"https://example.invalid/skills/{name}/SKILL.md",
        trust="community",
        stars=None,
        categories=(),
        languages=(),
        risk="monitor",
        tags=(),
    )


def _install(name: str) -> Path:
    return asyncio.run(SkillFinder().install(_candidate(name)))


def test_a_catalog_skill_is_stored_switched_off(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever state and schedule the file asks for, it lands as a draft."""
    _serve(monkeypatch, _skill_md("notes", extra=_SCHEDULED + "state: active\n"))
    path = _install("notes")

    skill = parse_skill(path)
    assert skill.state is SkillLifecycleState.DRAFT
    assert skill.name == "notes"
    # A draft is not put on a clock: no routine runs it until it is switched on.
    assert desired_schedules([skill]) == {}


def test_a_file_that_names_itself_otherwise_is_not_installed(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry keys a skill by the name inside the file; it must be the listed one."""
    _serve(monkeypatch, _skill_md("morning-routine"))
    with pytest.raises(RuntimeError, match="names itself"):
        _install("zz-notes")
    assert not (skills_dir / "zz-notes").exists()


def test_a_builtin_name_is_refused(skills_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.skills.builtin import BUILTIN_SKILL_NAMES

    name = sorted(BUILTIN_SKILL_NAMES)[0]
    _serve(monkeypatch, _skill_md(name))
    with pytest.raises(RuntimeError, match="built-in"):
        _install(name)
    assert not (skills_dir / name).exists()


def test_an_existing_skill_folder_is_never_replaced(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    own = skills_dir / "notes" / "SKILL.md"
    own.parent.mkdir()
    own.write_text(_skill_md("notes", extra="when_to_use: my own words\n"), encoding="utf-8")
    before = own.read_bytes()

    _serve(monkeypatch, _skill_md("notes"))
    with pytest.raises(RuntimeError, match="already exists"):
        _install("notes")
    assert own.read_bytes() == before


def test_an_oversized_file_is_refused_and_leaves_nothing(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    padding = "x" * (300 * 1024)
    _serve(monkeypatch, _skill_md("big", extra=f"when_to_use: {padding}\n"))
    with pytest.raises(RuntimeError, match="larger than"):
        _install("big")
    assert not (skills_dir / "big").exists()


def test_a_file_that_is_not_text_is_refused(
    skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, b"---\nname: bin\n---\n\xff\xfe\x00")
    with pytest.raises(RuntimeError):
        _install("bin")
    assert not (skills_dir / "bin").exists()


def test_a_dash_run_inside_a_value_keeps_the_draft_stamp(tmp_path: Path) -> None:
    """Three dashes inside a quoted value are text, for the stamp and the loader alike."""
    text = (
        "---\n"
        'schema_version: "1"\n'
        "name: dashes\n"
        'description: "a---b"\n'
        "---\n\n"
        "# Body\n"
    )
    stamped = _rewrite_state_in_frontmatter(text, SkillLifecycleState.DRAFT.value)
    path = tmp_path / "dashes" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(stamped, encoding="utf-8")

    skill = parse_skill(path)
    assert not skill.error
    assert skill.state is SkillLifecycleState.DRAFT
    assert skill.frontmatter is not None
    assert skill.frontmatter.description == "a---b"


def test_a_state_line_inside_a_value_does_not_count(tmp_path: Path) -> None:
    """Only the top-level key is the state; a look-alike line in a value is text."""
    text = (
        "---\n"
        'schema_version: "1"\n'
        "name: lookalike\n"
        "description: |\n"
        "  state: draft\n"
        "  is just a sentence here\n"
        "---\n\n"
        "# Body\n"
    )
    stamped = _rewrite_state_in_frontmatter(text, SkillLifecycleState.DRAFT.value)
    path = tmp_path / "lookalike" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(stamped, encoding="utf-8")

    skill = parse_skill(path)
    assert skill.state is SkillLifecycleState.DRAFT
    assert skill.frontmatter is not None
    assert skill.frontmatter.description.startswith("state: draft")
