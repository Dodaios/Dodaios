"""Import records (`verse.import/1`, art-pipeline 10.3): loading and paths. Pure Python."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from . import IMPORT_RECORDS, REPO_ROOT

SCHEMA_ID = "verse.import/1"


class RecordError(ValueError):
    """A record is missing, malformed or points at a missing export."""


def split_object_path(object_path: str) -> tuple[str, str]:
    """`/Game/Verse/Kit/A/SM_X.SM_X` -> (`/Game/Verse/Kit/A`, `SM_X`)."""
    package, _, obj = object_path.rpartition(".")
    folder, _, name = package.rpartition("/")
    if not folder or not name or obj != name:
        raise RecordError(f"not an object path of the form /Game/.../Name.Name: {object_path!r}")
    return folder, name


def load(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordError(f"{path}: {error}") from error
    if record.get("schema") != SCHEMA_ID:
        raise RecordError(f"{path}: schema must be {SCHEMA_ID}")
    record["_path"] = str(path)
    return record


def load_all(root: Path = IMPORT_RECORDS) -> list[dict]:
    if not root.is_dir():
        return []
    return [load(p) for p in sorted(root.rglob("*.import.json"))]


def select(records: Iterable[dict], only: Iterable[str] | None) -> list[dict]:
    """Records whose name is in `only` (all when `only` is empty); unknown names fail."""
    records = list(records)
    wanted = [n for n in (only or []) if n]
    if not wanted:
        return records
    by_name = {r["name"]: r for r in records}
    missing = [n for n in wanted if n not in by_name]
    if missing:
        raise RecordError(f"no import record for {', '.join(missing)}")
    return [by_name[n] for n in wanted]


def export_file(record: dict) -> Path:
    """The FBX or PNG the record was exported to (inside the ignored cache)."""
    path = REPO_ROOT / record["export"]["file"]
    if not path.is_file():
        raise RecordError(
            f"{record['name']}: export {record['export']['file']} is missing;"
            f" run python scripts/verse/export_unreal.py first"
        )
    return path
