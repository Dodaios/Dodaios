"""The Nodes library's cards (``dodaios/nodes/library.py``).

Every test builds real run directories and reads them through the same two
listings the app serves (``/api/outputs`` and ``/api/outputs/{slug}/artifacts``),
so a card here is what the app would show for that archive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.artifacts.living import LivingPageStore
from dodaios.artifacts.report import write_report
from dodaios.missions.standalone_run import write_marker
from dodaios.nodes import kinds as node_kinds
from dodaios.nodes import library, shell
from dodaios.nodes.kinds import NodeKind
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES

_NODE_MODEL = (
    Path(__file__).resolve().parents[3]
    / "dodaios/ui/web/frontend/src/components/nodes/nodeModel.ts"
)
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
_QUALITY_LEAD = (
    "Deliver a complete, polished, production-quality artifact that fully satisfies the "
    "request below."
)


def _kind(name: str, preview: Any = None) -> NodeKind:
    return NodeKind(
        type=name,
        normalize=lambda spec: spec,
        render=lambda node: shell.document(node, body="<main>x</main>"),
        preview=preview or (lambda spec: {"probe": 1}),
        starter=lambda title, language: {"probe": True},
        guide=f"guide for {name}",
    )


@pytest.fixture(autouse=True)
def kinds(monkeypatch: pytest.MonkeyPatch) -> dict[str, NodeKind]:
    """Stand-in renderers, so a card does not depend on a real type's layout."""
    fakes = {name: _kind(name) for name in NODE_TYPES}
    monkeypatch.setattr(node_kinds, "_KINDS", fakes)
    return fakes


# ------------------------------------------------------------------ an archive


class _Cursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    async def fetchone(self) -> Any:
        return self._cursor.fetchone()

    async def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    async def close(self) -> None:
        self._cursor.close()


class _Conn:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        return _Cursor(self._db.execute(sql, params))


class Missions:
    """Stands in for the mission manager: the run list reads ``.store.conn``."""

    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.execute(
            "CREATE TABLE missions (id TEXT, state TEXT, cost_usd REAL, updated_ms INTEGER, "
            "created_ms INTEGER, prompt TEXT, language TEXT)"
        )
        self._db.execute(
            "CREATE TABLE mission_events (seq INTEGER PRIMARY KEY, mission_id TEXT, "
            "event_type TEXT, payload_json TEXT)"
        )
        self.store = SimpleNamespace(conn=_Conn(self._db))

    def add(
        self,
        mission_id: str,
        state: str,
        prompt: str,
        *,
        started: float,
        ended: float | None = None,
        summary: str = "",
    ) -> str:
        """Record a mission; returns the name of its run directory."""
        end = ended if ended is not None else started
        self._db.execute(
            "INSERT INTO missions VALUES (?, ?, 0, ?, ?, ?, 'en')",
            (mission_id, state, int(end * 1000), int(started * 1000), prompt),
        )
        if state == "APPROVED":
            self._db.execute(
                "INSERT INTO mission_events (mission_id, event_type, payload_json) VALUES (?,?,?)",
                (mission_id, "MissionApproved", json.dumps({"summary_en": summary})),
            )
        if state == "FAILED":
            self._db.execute(
                "INSERT INTO mission_events (mission_id, event_type, payload_json) VALUES (?,?,?)",
                (mission_id, "MissionFailed", json.dumps({"reason": "worker_crashed"})),
            )
        return f"mission_{mission_id[:13]}"


def _files(root: Path, slug: str, files: dict[str, str | bytes], *, mtime: float = 0.0) -> Path:
    """Write deliverables into ``<slug>/tasks/t1/artifacts/files`` plus worker scaffolding."""
    run_dir = root / slug
    for name, content in files.items():
        target = run_dir / "tasks" / "t1" / "artifacts" / "files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        if mtime:
            os.utime(target, (mtime, mtime))
    # What a worker leaves beside its deliverables; none of it is a card.
    (run_dir / "tasks" / "t1" / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "tasks" / "t1" / "logs" / "stream.jsonl").write_text("{}\n", encoding="utf-8")
    (run_dir / "claude_config").mkdir(exist_ok=True)
    (run_dir / "claude_config" / "settings.html").write_text("<title>No</title>", encoding="utf-8")
    (run_dir / "reflections.md").write_text("internal", encoding="utf-8")
    return run_dir


def _html(title: str | None, body: str = "<p>content</p>") -> str:
    head = f"<title>{title}</title>" if title is not None else ""
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def _request(root: Path, missions: Missions | None = None) -> Any:
    state = SimpleNamespace(outputs_root=root, mission_manager=missions)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _library(root: Path, missions: Missions | None = None, **options: Any) -> dict[str, Any]:
    request = _request(root, missions)
    store = NodeStore(root=root)
    return library.build_library(
        request,
        runs=asyncio.run(library.list_runs(request)),
        nodes=store.list_nodes(),
        store=store,
        living_store=LivingPageStore(root=root),
        **options,
    )


def _by_key(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = [card["key"] for card in result["nodes"]]
    assert len(keys) == len(set(keys)), "card keys must be unique"
    return {card["key"]: card for card in result["nodes"]}


# ------------------------------------------------------------------ text rules


def test_visual_kinds_follow_the_file_extension() -> None:
    assert library.visual_kind("tasks/t1/artifacts/files/Board.HTML") == "page"
    assert library.visual_kind("a/b/page.htm") == "page"
    for name in ("a.png", "a.jpg", "a.JPEG", "a.gif", "a.webp", "a.bmp", "a.avif"):
        assert library.visual_kind(name) == "image"
    assert library.visual_kind("logo.svg") == "vector"
    assert library.visual_kind("paper.pdf") == "document"
    for name in ("notes.md", "data.csv", "clip.mp4", "deck.pptx", "html", "page.html.bak"):
        assert library.visual_kind(name) is None


def test_a_brief_is_recognised_by_its_lead_line() -> None:
    assert library.brief_title("Artifact: Sales dashboard\nShow my sales.") == "Sales dashboard"
    assert library.brief_title("  Artifact:\tQ3 \n\nrest") == "Q3"
    assert library.brief_title("Make an artifact: a chart") is None
    assert library.brief_title("artifact: lower case") is None
    assert library.brief_title("") is None and library.brief_title(None) is None


def test_a_request_loses_the_workers_tail_and_becomes_a_headline() -> None:
    asked = (
        "Compare  the three\nlaptops. Supporting context from the recent conversation "
        "(use only to resolve references): - earlier turn"
    )
    assert library.clean_request(asked) == "Compare the three laptops."
    assert library.request_headline("Short ask") == "Short ask"

    long_first = "Find me a flight to Lisbon in May. " + "It should leave early. " * 10
    assert library.request_headline(long_first) == "Find me a flight to Lisbon in May."
    one_sentence = "compare " + "the laptops and " * 12 + "then stop"
    headline = library.request_headline(one_sentence)
    assert headline.endswith("…") and len(headline) <= library.HEADLINE_MAX_CHARS + 1
    assert not headline[:-1].endswith((" ", ","))

    assert library.run_title({"slug": "s", "utterance": "Artifact: Board\nmake it"}) == "Board"
    assert library.run_title({"slug": "s", "utterance": "Plan my week"}) == "Plan my week"
    assert library.run_title({"slug": "mission_abc", "utterance": None}) == "mission_abc"


# ------------------------------------------------------------------ typed nodes


def test_a_typed_node_is_a_card_with_its_preview(tmp_path: Path) -> None:
    store = NodeStore(root=tmp_path)
    node = store.create(type="sheets", title="Open orders", spec={"rows": [1]}, now=1_000.0)
    node = store.update(node.id, spec={"rows": [1, 2]}, now=2_000.0)
    node = store.set_upkeep(node.id, track="the shop's orders", every_minutes=45, refreshing=True)

    result = _library(tmp_path)
    assert result == {
        "nodes": [
            {
                "key": f"{node.slug}::{node.page_path}",
                "id": node.id,
                "type": "sheets",
                "origin": "node",
                "title": "Open orders",
                "slug": node.slug,
                "path": node.page_path,
                "visual_kind": "page",
                "created_at": 1_000.0,
                "updated_at": 2_000.0,
                "size": (tmp_path / node.slug / node.page_path).stat().st_size,
                "version": 2,
                "status": "ready",
                "kept_current": True,
                "refreshing": True,
                "every_minutes": 45,
                "request": "",
                "preview": {"probe": 1},
            }
        ],
        # A node's own run is never searched for files to adopt.
        "scanned_runs": 0,
        "skipped_runs": 0,
    }
    assert result["nodes"][0]["size"] > 0


def test_a_node_nobody_keeps_current_does_not_claim_a_refresh(tmp_path: Path) -> None:
    store = NodeStore(root=tmp_path)
    node = store.create(type="docs", title="Plan", spec={})
    store.set_upkeep(node.id, refreshing=True, every_minutes=30)  # a record without a track

    card = _library(tmp_path)["nodes"][0]
    assert (card["kept_current"], card["refreshing"], card["every_minutes"]) == (False, False, 0)


def test_a_preview_that_raises_does_not_take_the_list_down(
    tmp_path: Path, kinds: dict[str, NodeKind], caplog: pytest.LogCaptureFixture
) -> None:
    def faulty(spec: dict[str, Any]) -> dict[str, Any]:
        raise KeyError("columns")

    kinds["sheets"] = _kind("sheets", preview=faulty)
    store = NodeStore(root=tmp_path)
    broken = store.create(type="sheets", title="Broken", spec={})
    fine = store.create(type="docs", title="Fine", spec={})

    with caplog.at_level(logging.WARNING, logger="dodaios.nodes.library"):
        cards = _by_key(_library(tmp_path))
    assert cards[broken.visual_id]["preview"] is None
    assert cards[broken.visual_id]["title"] == "Broken"
    assert cards[fine.visual_id]["preview"] == {"probe": 1}
    assert broken.id in caplog.text


# --------------------------------------------------------------------- adopted


def test_older_runs_are_adopted_under_the_closest_type(tmp_path: Path) -> None:
    node = NodeStore(root=tmp_path).create(type="slides", title="Kickoff", spec={})
    pages = LivingPageStore(root=tmp_path)
    living = pages.create(
        title="Parcels",
        track="my parcels",
        columns=["Parcel"],
        rows=[{"Parcel": "A"}],
        every_minutes=45,
        now=1_700_000_000.0,
    )
    pages.set_refresh(living.id, refreshing=True, task_id="task-1")
    report = write_report(
        title="Market report",
        markdown="## One\n\nText.",
        summary="Short.",
        root=tmp_path,
        now=1_700_000_100.0,
    )
    _files(
        tmp_path,
        "mission_aaaaaaaa1111",
        {
            "dashboard.html": _html("Sales &amp; costs"),
            "img/chart.png": _PNG,
            "logo.SVG": "<svg xmlns='http://www.w3.org/2000/svg'/>",
            "paper.pdf": b"%PDF-1.4\n",
            "notes.txt": "not a visual",
            "data.csv": "a,b\n1,2\n",
        },
        mtime=1_700_000_200.0,
    )

    result = _library(tmp_path)
    cards = _by_key(result)
    assert (result["scanned_runs"], result["skipped_runs"]) == (3, 0)
    files = "tasks/t1/artifacts/files"
    assert set(cards) == {
        node.visual_id,
        living.visual_id,
        f"{report.slug}::{report.page_path}",
        f"mission_aaaaaaaa1111::{files}/dashboard.html",
        f"mission_aaaaaaaa1111::{files}/img/chart.png",
        f"mission_aaaaaaaa1111::{files}/logo.SVG",
        f"mission_aaaaaaaa1111::{files}/paper.pdf",
    }
    assert [card["origin"] for card in cards.values()].count("node") == 1

    card = cards[living.visual_id]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("sheets", "living", "page")
    assert (card["kept_current"], card["refreshing"], card["every_minutes"]) == (True, True, 45)
    assert (card["title"], card["request"], card["slug"]) == ("Parcels", "Parcels", living.slug)
    assert card["path"] == living.page_path and card["created_at"] == 1_700_000_000.0
    assert (card["id"], card["version"], card["preview"]) == (None, 0, None)
    assert card["status"] == "ready"
    assert card["size"] == (tmp_path / living.slug / living.page_path).stat().st_size

    card = cards[f"{report.slug}::{report.page_path}"]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("docs", "report", "page")
    assert card["title"] == "Market report"
    assert (card["kept_current"], card["refreshing"]) == (False, False)
    assert card["created_at"] == 1_700_000_100.0

    card = cards[f"mission_aaaaaaaa1111::{files}/dashboard.html"]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("design", "page", "page")
    assert (card["title"], card["request"], card["status"]) == ("Sales & costs", "", "ready")
    assert card["updated_at"] == 1_700_000_200.0 and card["preview"] is None

    card = cards[f"mission_aaaaaaaa1111::{files}/img/chart.png"]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("design", "file", "image")
    assert (card["title"], card["size"]) == ("chart.png", len(_PNG))
    card = cards[f"mission_aaaaaaaa1111::{files}/logo.SVG"]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("design", "file", "vector")
    card = cards[f"mission_aaaaaaaa1111::{files}/paper.pdf"]
    assert (card["type"], card["origin"], card["visual_kind"]) == ("docs", "file", "document")
    assert card["title"] == "paper.pdf"


def test_a_living_page_without_its_state_is_still_a_card(tmp_path: Path) -> None:
    pages = LivingPageStore(root=tmp_path)
    living = pages.create(title="Jobs", track="applications", columns=["Company"])
    (tmp_path / living.slug / "living-page.json").unlink()

    card = _by_key(_library(tmp_path))[living.visual_id]
    assert (card["type"], card["origin"], card["kept_current"]) == ("sheets", "living", True)
    assert (card["refreshing"], card["every_minutes"]) == (False, 0)


def test_a_page_is_named_by_its_title_then_its_brief_then_its_file(tmp_path: Path) -> None:
    files = "tasks/t1/artifacts/files"
    one = "20260301T100000__sales__aaaaaa01"
    _files(tmp_path, one, {"sales.html": _html(None), "chart.png": _PNG})
    write_marker(
        tmp_path / one,
        kind="artifact",
        utterance="Artifact: Sales dashboard\nShow my sales by month.\n\n## What to build\nX",
    )
    two = "20260301T110000__pair__aaaaaa02"
    _files(tmp_path, two, {"first.html": _html(None), "second.html": _html("  Second \n page ")})
    write_marker(tmp_path / two, kind="artifact", utterance="Artifact: A pair\nTwo pages.")
    big = "20260301T120000__big__aaaaaa03"
    _files(tmp_path, big, {"big.html": _html("Big page", body="<p>x</p>" * 6_000)})
    write_marker(tmp_path / big, kind="artifact", utterance="Plain request for a big page")

    cards = _by_key(_library(tmp_path))
    # The only page of a brief run takes the brief's title; its picture does not.
    assert cards[f"{one}::{files}/sales.html"]["title"] == "Sales dashboard"
    assert cards[f"{one}::{files}/chart.png"]["title"] == "chart.png"
    assert cards[f"{one}::{files}/sales.html"]["request"] == "Sales dashboard"
    assert cards[f"{one}::{files}/sales.html"]["created_at"] == 1_772_359_200.0
    # Two pages: the brief names neither.
    assert cards[f"{two}::{files}/first.html"]["title"] == "first.html"
    assert cards[f"{two}::{files}/second.html"]["title"] == "Second page"
    # A page too large for the listing's text preview still states its title.
    assert cards[f"{big}::{files}/big.html"]["title"] == "Big page"
    assert cards[f"{big}::{files}/big.html"]["request"] == "Plain request for a big page"
    assert {card["status"] for card in cards.values()} == {"ready"}


# ------------------------------------------------------- builds and plain runs


def test_a_page_still_being_built_is_a_build_card_until_it_lands(tmp_path: Path) -> None:
    missions = Missions()
    brief = f"{_QUALITY_LEAD}\n\nArtifact: Sales dashboard\nShow my sales.\n\n## What to build\nX"
    slug = missions.add("019f0000-aaa1-7000-8000-000000000001", "RUNNING", brief, started=5_000.0)
    _files(tmp_path, slug, {})

    result = _library(tmp_path, missions)
    assert result["nodes"] == [
        {
            "key": f"build:{slug}",
            "id": None,
            "type": "design",
            "origin": "build",
            "title": "Sales dashboard",
            "slug": slug,
            "path": None,
            "visual_kind": None,
            "created_at": result["nodes"][0]["created_at"],
            "updated_at": result["nodes"][0]["updated_at"],
            "size": 0,
            "version": 0,
            "status": "building",
            "kept_current": False,
            "refreshing": False,
            "every_minutes": 0,
            "request": "Sales dashboard",
            "preview": None,
        }
    ]

    # A picture alone is not the page that was asked for.
    _files(tmp_path, slug, {"draft.png": _PNG})
    cards = _by_key(_library(tmp_path, missions))
    assert set(cards) == {f"build:{slug}", f"{slug}::tasks/t1/artifacts/files/draft.png"}

    _files(tmp_path, slug, {"sales-dashboard.html": _html(None)})
    cards = _by_key(_library(tmp_path, missions))
    page = cards[f"{slug}::tasks/t1/artifacts/files/sales-dashboard.html"]
    assert f"build:{slug}" not in cards and f"run:{slug}" not in cards
    assert (page["title"], page["status"], page["origin"]) == ("Sales dashboard", "ready", "page")


def test_a_run_with_nothing_to_look_at_is_a_card_with_its_answer(tmp_path: Path) -> None:
    missions = Missions()
    answered = missions.add(
        "019f0000-bbb1-7000-8000-000000000001",
        "APPROVED",
        f"{_QUALITY_LEAD}\n\nWhich flight to Lisbon is the cheapest in May?",
        started=1_000.0,
        ended=1_600.0,
        summary="The cheapest flight leaves on Tuesday. " * 12,
    )
    _files(tmp_path, answered, {"answer.md": "# Flights\n\nA long table follows."})
    written = _files(tmp_path, "mission_cccccccc0001", {"answer.md": "# Findings\n\n- one\n- two"})
    failed = missions.add(
        "019f0000-ddd1-7000-8000-000000000001", "FAILED", "Book the trip", started=2_000.0
    )
    _files(tmp_path, failed, {})
    working = missions.add(
        "019f0000-eee1-7000-8000-000000000001", "RUNNING", "Research the market", started=3_000.0
    )
    _files(tmp_path, working, {})

    cards = _by_key(_library(tmp_path, missions))
    assert set(cards) == {
        f"run:{answered}",
        f"run:{written.name}",
        f"run:{failed}",
        f"run:{working}",
    }
    for card in cards.values():
        assert (card["type"], card["origin"]) == ("output", "run")
        assert (card["path"], card["visual_kind"]) == (None, None)
        assert (card["id"], card["size"]) == (None, 0)

    card = cards[f"run:{answered}"]
    assert card["title"] == card["request"] == "Which flight to Lisbon is the cheapest in May?"
    assert card["status"] == "ready"
    assert (card["created_at"], card["updated_at"]) == (card["created_at"], 1_600.0)
    text = card["preview"]["text"]
    assert text.startswith("The cheapest flight leaves on Tuesday. The cheapest")
    assert len(text) == library.MAX_PREVIEW_CHARS and text.endswith("…")

    # No summary: the first lines of the answer the run wrote down.
    card = cards[f"run:{written.name}"]
    assert card["preview"] == {"text": "Findings - one - two"}
    assert card["title"] == written.name and card["request"] == ""

    assert cards[f"run:{failed}"]["status"] == "error"
    assert cards[f"run:{failed}"]["preview"] == {"text": ""}
    assert cards[f"run:{working}"]["status"] == "building"
    assert cards[f"run:{working}"]["title"] == "Research the market"


def test_a_failed_run_keeps_its_page_and_says_it_failed(tmp_path: Path) -> None:
    missions = Missions()
    slug = missions.add("019f0000-fff1-7000-8000-000000000001", "FAILED", "A page", started=1.0)
    _files(tmp_path, slug, {"page.html": _html("Half a page")})

    (card,) = _library(tmp_path, missions)["nodes"]
    assert (card["origin"], card["status"], card["title"]) == ("page", "error", "Half a page")


# --------------------------------------------------------------- order, window


def test_work_in_progress_leads_then_the_newest_change(tmp_path: Path) -> None:
    missions = Missions()
    store = NodeStore(root=tmp_path)
    old_node = store.create(type="docs", title="Old node", spec={}, now=1_000.0)
    new_node = store.create(type="docs", title="New node", spec={}, now=4_000.0)
    _files(tmp_path, "mission_aaaaaaaa0001", {"mid.html": _html("Mid page")}, mtime=3_000.0)
    _files(tmp_path, "mission_aaaaaaaa0002", {"old.png": _PNG}, mtime=2_000.0)
    building = missions.add(
        "019f0000-aaa2-7000-8000-000000000001", "RUNNING", "Artifact: Soon\nx", started=500.0
    )
    _files(tmp_path, building, {})

    cards = _library(tmp_path, missions)["nodes"]
    assert [card["title"] for card in cards] == [
        "Soon",
        "New node",
        "Mid page",
        "old.png",
        "Old node",
    ]
    assert cards[0]["status"] == "building"
    assert {cards[1]["id"], cards[4]["id"]} == {new_node.id, old_node.id}


def test_only_the_newest_runs_are_searched_for_files(tmp_path: Path) -> None:
    store = NodeStore(root=tmp_path)
    for index in range(3):
        store.create(type="docs", title=f"Node {index}", spec={})
    slugs = [f"20260301T10000{index}__run-{index}__aaaaaa0{index}" for index in range(5)]
    for index, slug in enumerate(slugs):
        _files(tmp_path, slug, {"page.html": _html(f"Page {index}")})
        write_marker(tmp_path / slug, kind="visualization", utterance=f"Request {index}")

    result = _library(tmp_path, scan_limit=2)
    cards = _by_key(result)
    # Typed nodes do not use up the window.
    assert (result["scanned_runs"], result["skipped_runs"]) == (2, 3)
    assert sum(1 for card in cards.values() if card["origin"] == "node") == 3
    for slug in slugs[3:]:
        assert cards[f"{slug}::tasks/t1/artifacts/files/page.html"]["origin"] == "page"
    # A run outside the window keeps a card; its files are read when it is opened.
    for index, slug in enumerate(slugs[:3]):
        card = cards[f"run:{slug}"]
        assert (card["origin"], card["title"], card["preview"]) == (
            "run",
            f"Request {index}",
            {"text": ""},
        )

    everything = _library(tmp_path, scan_limit=10_000)
    assert (everything["scanned_runs"], everything["skipped_runs"]) == (5, 0)
    assert _library(tmp_path, scan_limit=0)["scanned_runs"] == 1
    assert library.DEFAULT_SCAN_LIMIT == 60 and library.MAX_SCAN_LIMIT == 500


def test_a_run_that_vanished_since_the_run_list_was_read_does_not_fail(tmp_path: Path) -> None:
    _files(tmp_path, "mission_aaaaaaaa0001", {"page.html": _html("Still here")})
    request = _request(tmp_path)
    runs = asyncio.run(library.list_runs(request))
    runs.append({"slug": "mission_bbbbbbbb0002", "utterance": "Gone", "status": "success"})
    runs.append({"slug": "../outside", "utterance": "Not a run", "status": "success"})

    store = NodeStore(root=tmp_path)
    result = library.build_library(request, runs=runs, nodes=[], store=store)
    assert [card["title"] for card in result["nodes"]] == ["Still here", "Gone", "Not a run"]
    assert result["scanned_runs"] == 3


def test_internal_worker_files_are_never_adopted(tmp_path: Path) -> None:
    run_dir = _files(tmp_path, "mission_aaaaaaaa0001", {"page.html": _html("Real")})
    (run_dir / "tasks" / "t1" / "artifacts" / "diff.html").write_text(_html("Diff"), "utf-8")
    (run_dir / "cover.png").write_bytes(_PNG)

    assert [card["title"] for card in _library(tmp_path)["nodes"]] == ["Real"]


# ------------------------------------------------------------ frontend contract


def _interface(source: str, name: str) -> str:
    match = re.search(rf"export interface {name} \{{\n(.*?)\n\}}", source, re.DOTALL)
    assert match is not None, f"{name} not found in nodeModel.ts"
    return match.group(1)


def _union(source: str, name: str) -> set[str]:
    code = re.sub(r"//[^\n]*", "", source)
    match = re.search(rf"export type {name} =(.*?);", code, re.DOTALL)
    assert match is not None, f"{name} not found in nodeModel.ts"
    return set(re.findall(r'"([a-z]+)"', match.group(1)))


def test_cards_match_the_frontends_node_card(tmp_path: Path) -> None:
    source = _NODE_MODEL.read_text(encoding="utf-8")
    fields = re.findall(r"^  (\w+)\??:", _interface(source, "NodeCard"), re.MULTILINE)
    origins = _union(source, "NodeOrigin")
    visual_kinds = _union(source, "NodeVisualKind")

    missions = Missions()
    NodeStore(root=tmp_path).create(type="docs", title="Node", spec={})
    LivingPageStore(root=tmp_path).create(title="Living", track="x", columns=["A"])
    write_report(title="Report", markdown="Text.", root=tmp_path)
    _files(tmp_path, "mission_aaaaaaaa0001", {"p.html": _html("P"), "a.png": _PNG, "b.pdf": b"%"})
    _files(tmp_path, "mission_aaaaaaaa0002", {"logo.svg": "<svg/>"})
    _files(tmp_path, "mission_aaaaaaaa0003", {"answer.md": "Text"})
    build = missions.add(
        "019f0000-aaa3-7000-8000-000000000001", "RUNNING", "Artifact: B", started=1.0
    )
    _files(tmp_path, build, {})

    result = _library(tmp_path, missions)
    assert set(result) == set(
        re.findall(r"^  (\w+):", _interface(source, "NodesResponse"), re.MULTILINE)
    )
    for card in result["nodes"]:
        assert list(card) == fields
        assert card["type"] in (*NODE_TYPES, "output")
        assert card["visual_kind"] is None or card["visual_kind"] in visual_kinds
        assert card["status"] in ("ready", "building", "error")
        assert (card["path"] is None) == (card["visual_kind"] is None)
        assert (card["id"] is not None) == (card["origin"] == "node")
        assert card["preview"] is None or isinstance(card["preview"], dict)
    assert {card["origin"] for card in result["nodes"]} == origins
    assert {card["visual_kind"] for card in result["nodes"]} == {*visual_kinds, None}
    assert {extension_kind for _, extension_kind in library.VISUAL_EXTENSIONS} == visual_kinds
    json.dumps(result)  # the whole answer is plain JSON
