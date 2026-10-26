"""The repo-junk gate blocks films, masters and oversized files, not product code."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_repo_junk.py"
_spec = importlib.util.spec_from_file_location("check_repo_junk", _PATH)
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

MB = 1024 * 1024


def test_blocks_videos_masters_and_archives() -> None:
    paths = {
        "assets/demo/hero.mp4": 10,
        "dodaios/ui/web/frontend/public/clip.webm": 10,
        "art/studies/city/source/city.blend": 10,
        "marketing/brand.psd": 10,
        "release/bundle.zip": 10,
        "assets/icons/app.ico.backup": 10,
    }
    found = gate.problems(paths, [])
    assert len(found) == len(paths)


def test_blocks_working_folders_and_oversized_files() -> None:
    found = gate.problems(
        {
            "video/src/Scene.tsx": 10,
            "art/studies/city/evidence/shot.png": 10,
            "docs/huge-diagram.png": 6 * MB,
        },
        [],
    )
    assert len(found) == 3


def test_product_files_and_allowlisted_assets_pass() -> None:
    paths = {
        "dodaios/core/config.py": 10,
        "dodaios/ui/web/frontend/src/App.tsx": 10,
        "dodaios/appshot/video_encoder.py": 10,
        "dodaios/ui/web/dist/assets/ort-wasm.wasm": 14 * MB,
        "assets/demo/readme/dodaios-demo.gif": 3 * MB,
    }
    allow = ["dodaios/ui/web/dist/*", "assets/demo/readme/dodaios-demo.gif"]
    assert gate.problems(paths, allow) == []


def test_current_tree_is_clean() -> None:
    assert gate.problems(gate._tracked_sizes(), gate._load_allowlist()) == []
