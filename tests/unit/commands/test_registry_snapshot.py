"""Characterization test: the full command registry, in order, against a snapshot.

Guards structural refactors of ``dodaios/commands`` (splitting definitions across
modules must not change a command, its order, or any field).

The snapshot keeps ids, titles, endpoints, flags and English voice aliases readable.
Free text that may quote spoken German examples (descriptions, the params schema,
non-English voice aliases) is stored as a SHA-256 digest so the file stays English-only.
Regenerate after an intended change with::

    python tests/unit/commands/test_registry_snapshot.py --write
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from dodaios.commands.registry import registry_as_dicts

SNAPSHOT = Path(__file__).with_name("registry_snapshot.json")


def _digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot_rows() -> list[dict[str, Any]]:
    rows = registry_as_dicts()
    out: list[dict[str, Any]] = []
    for row in rows:
        slim = {k: v for k, v in row.items() if k not in ("description", "params", "voice_aliases")}
        slim["description_sha256"] = _digest(row["description"])
        slim["params_sha256"] = _digest(row["params"])
        slim["voice_aliases"] = {
            loc: (v if loc == "en" else _digest(v)) for loc, v in row["voice_aliases"].items()
        }
        out.append(slim)
    return out


def _current() -> str:
    return json.dumps(_snapshot_rows(), indent=1, ensure_ascii=False) + "\n"


def test_registry_matches_snapshot() -> None:
    assert _current() == SNAPSHOT.read_text(encoding="utf-8")


if __name__ == "__main__":
    if "--write" in sys.argv:
        SNAPSHOT.write_text(_current(), encoding="utf-8", newline="\n")
