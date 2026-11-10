"""The computers file keeps a record this version cannot read.

An unreadable record used to be skipped on read and was then gone with the
next write of any other record: one bad field deleted a computer for good.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dodaios.computers.models import Computer
from dodaios.computers.store import ComputerStore

GOOD = {"id": "c_good", "name": "good", "host": "203.0.113.5", "created_at": 1.0}
#: A record with a port no version accepts, standing in for any entry that
#: fails validation (a newer version's field, a hand edit).
BAD = {"id": "c_bad", "name": "from elsewhere", "host": "203.0.113.9", "port": "not a port"}


def _file(path: Path, *records: Any) -> None:
    path.write_text(json.dumps({"version": 1, "computers": list(records)}), encoding="utf-8")


def _on_disk(path: Path) -> list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))["computers"]


def test_an_unreadable_record_is_not_listed(tmp_path: Path) -> None:
    path = tmp_path / "computers.json"
    _file(path, GOOD, BAD)

    assert [c.id for c in ComputerStore(path).all()] == ["c_good"]


def test_an_unreadable_record_survives_an_update_of_another(tmp_path: Path) -> None:
    path = tmp_path / "computers.json"
    _file(path, BAD, GOOD)
    store = ComputerStore(path)

    store.update("c_good", lambda row: row.model_copy(update={"name": "renamed"}))

    on_disk = _on_disk(path)
    assert BAD in on_disk, "kept exactly as it was written"
    assert [r["name"] for r in on_disk if r["id"] == "c_good"] == ["renamed"]


def test_an_unreadable_record_survives_add_and_remove(tmp_path: Path) -> None:
    path = tmp_path / "computers.json"
    _file(path, GOOD, BAD)
    store = ComputerStore(path)

    store.add(Computer(id="c_new", name="new", host="10.0.0.2", created_at=2.0))
    assert store.remove("c_good") is True

    on_disk = _on_disk(path)
    assert BAD in on_disk
    assert [r["id"] for r in on_disk if r != BAD] == ["c_new"]
    assert [c.id for c in store.all()] == ["c_new"]


def test_an_entry_that_is_no_record_at_all_is_kept_too(tmp_path: Path) -> None:
    path = tmp_path / "computers.json"
    _file(path, "a stray string", GOOD)
    store = ComputerStore(path)

    store.update("c_good", lambda row: row)

    assert "a stray string" in _on_disk(path)


def test_a_computers_field_that_is_no_list_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "computers.json"
    path.write_text(json.dumps({"version": 1, "computers": {"id": "c_1"}}), encoding="utf-8")

    assert ComputerStore(path).all() == []
