#!/usr/bin/env python3
"""Create the PrimaryAssetLabel of every deck chunk (WP22.3).

The engine's Map rules in ``DefaultGame.ini`` do not move a level's assets into
its own IoStore chunk on 5.7 (every package stays in chunk 0), but a
PrimaryAssetLabel that labels the assets in its folder does. One label per deck
sits next to the deck's level, named ``PAL_<Deck>``, with the chunk id of
``unreal/Toolchain/chunks.json``.

    python scripts/unreal/deck_labels.py            # create the missing labels
    python scripts/unreal/deck_labels.py --print    # print the editor script only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import with_lock

CHUNKS_FILE = common.UNREAL_ROOT / "Toolchain" / "chunks.json"


def deck_labels(chunks: dict[str, Any]) -> list[dict[str, Any]]:
    """``[{"folder": "/Game/Verse/Decks/Bridge", "name": "PAL_Bridge", "chunk": 1}, ...]``."""
    labels = []
    for chunk in sorted(chunks["chunks"], key=lambda c: c["id"]):
        for level in chunk.get("maps", []):
            folder, _, level_name = level.rpartition("/")
            labels.append(
                {
                    "folder": folder,
                    "name": "PAL_" + level_name.removeprefix("LV_"),
                    "chunk": chunk["id"],
                    "priority": 10 + chunk["id"],
                }
            )
    return labels


def editor_script(labels: Sequence[dict[str, Any]]) -> str:
    return f"""import unreal

LABELS = {json.dumps(list(labels))}
tools = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.DataAssetFactory()
factory.set_editor_property("data_asset_class", unreal.PrimaryAssetLabel)
for item in LABELS:
    path = item["folder"] + "/" + item["name"]
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.log("deck_labels: " + path + " exists")
        continue
    asset = tools.create_asset(item["name"], item["folder"], unreal.PrimaryAssetLabel, factory)
    asset.set_editor_property("label_assets_in_my_directory", True)
    rules = asset.get_editor_property("rules")
    rules.set_editor_property("priority", item["priority"])
    rules.set_editor_property("chunk_id", item["chunk"])
    rules.set_editor_property("apply_recursively", True)
    asset.set_editor_property("rules", rules)
    unreal.EditorAssetLibrary.save_asset(path)
    unreal.log("deck_labels: made " + path)
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="print_only")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    options = parser.parse_args(argv)
    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    script = editor_script(deck_labels(chunks))
    if options.print_only:
        print(script, end="")
        return 0
    worktree = options.worktree.resolve()
    target = worktree / "unreal" / "Verse" / "Saved" / "deck_labels.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script, encoding="utf-8")
    command = [
        str(common.editor_cmd(common.engine_root())),
        str(common.project_file(worktree)),
        "-nullrhi",
        "-unattended",
        "-nosplash",
        f"-ExecutePythonScript={target}",
    ]
    return with_lock.run_locked(command, label=f"deck labels ({worktree.name})", cwd=worktree)


if __name__ == "__main__":
    raise SystemExit(main())
