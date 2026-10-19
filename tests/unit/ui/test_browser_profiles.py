"""The IDE browser panel's browser discovery, profile list, window marker and geometry."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from dodaios.ui import browser_profiles as cp


def _install(root: Path, relpath: str) -> None:
    exe = root / relpath
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")


def _local_state(user_data: Path, profile: dict) -> None:
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "Local State").write_text(json.dumps({"profile": profile}), encoding="utf-8")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "PROGRAMFILES": str(tmp_path / "pf"),
        "PROGRAMFILES(X86)": str(tmp_path / "pf86"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }


def test_profiles_keep_the_pickers_order_and_skip_hidden_ones(tmp_path: Path) -> None:
    user_data = tmp_path / "User Data"
    _local_state(user_data, {
        "info_cache": {
            "Default": {"name": "Work", "user_name": "me@work.example"},
            "Profile 2": {"name": "Home", "user_name": ""},
            "Profile 9": {"name": "Gone", "is_omitted_from_profile_list": True},
            "Guest Profile": {"name": "Guest", "is_ephemeral": True},
        },
        "profiles_order": ["Profile 2", "Default"],
        "last_used": "Default",
    })
    profiles, last_used = cp.read_profiles(user_data)
    assert [p.directory for p in profiles] == ["Profile 2", "Default"]
    assert profiles[1].email == "me@work.example"
    assert last_used == "Default"


def test_profiles_without_an_order_are_sorted_and_last_used_falls_back(tmp_path: Path) -> None:
    user_data = tmp_path / "User Data"
    _local_state(user_data, {
        "info_cache": {"Profile 3": {"name": "beta"}, "Profile 1": {"name": "Alpha"}},
        "last_used": "Profile 99",
    })
    profiles, last_used = cp.read_profiles(user_data)
    assert [p.name for p in profiles] == ["Alpha", "beta"]
    assert last_used == "Profile 1"


@pytest.mark.parametrize("content", ["not json", json.dumps([1, 2]), json.dumps({"profile": 3})])
def test_a_broken_local_state_gives_no_profiles(tmp_path: Path, content: str) -> None:
    user_data = tmp_path / "User Data"
    user_data.mkdir()
    (user_data / "Local State").write_text(content, encoding="utf-8")
    assert cp.read_profiles(user_data) == ([], None)


def test_missing_local_state_gives_no_profiles(tmp_path: Path) -> None:
    assert cp.read_profiles(tmp_path / "nothing") == ([], None)
    assert cp.read_profiles(None) == ([], None)


def test_installed_browsers_lists_only_installed_ones_with_profiles(env: dict[str, str]) -> None:
    _install(Path(env["PROGRAMFILES"]), r"Google\Chrome\Application\chrome.exe")
    _install(Path(env["LOCALAPPDATA"]), r"BraveSoftware\Brave-Browser\Application\brave.exe")
    _local_state(Path(env["LOCALAPPDATA"]) / r"Google\Chrome\User Data", {
        "info_cache": {"Profile 3": {"name": "Profil 1", "user_name": "a@b.example"}},
        "last_used": "Profile 3",
    })
    found = cp.installed_browsers(env)
    assert [b["id"] for b in found] == ["chrome", "brave"]
    assert found[0]["profiles"] == [
        {"directory": "Profile 3", "name": "Profil 1", "email": "a@b.example"},
    ]
    assert found[0]["last_used"] == "Profile 3"
    # A browser that never ran still offers its default profile.
    assert found[1]["profiles"][0]["directory"] == "Default"
    assert found[1]["last_used"] == "Default"


def test_no_browser_installed(env: dict[str, str]) -> None:
    assert cp.installed_browsers(env) == []


def test_image_name_is_the_exe_file_name() -> None:
    assert cp.browser_by_id("chrome").image_name == "chrome.exe"  # type: ignore[union-attr]
    assert cp.browser_by_id("edge").image_name == "msedge.exe"  # type: ignore[union-attr]
    assert cp.browser_by_id("nope") is None


@pytest.mark.parametrize(("value", "ok"), [
    ("Default", True),
    ("Profile 12", True),
    ("Guest Profile", True),
    ("--user-data-dir=x", False),
    ("..\\..\\Windows", False),
    ("a/b", False),
    ("", False),
    ("Default\n", False),
    (".", False),
    ("Profile 1.", False),
    (" Default", False),
])
def test_profile_dir_names(value: str, ok: bool) -> None:
    assert cp.is_profile_dir(value) is ok


@pytest.mark.parametrize(("url", "expected"), [
    ("https://github.com/", "https://github.com/"),
    ("  http://localhost:5173/x  ", "http://localhost:5173/x"),
    ("javascript:alert(1)", cp.DEFAULT_START_URL),
    ("file:///C:/secret.txt", cp.DEFAULT_START_URL),
    ("chrome://settings", cp.DEFAULT_START_URL),
    ("", cp.DEFAULT_START_URL),
    (None, cp.DEFAULT_START_URL),
])
def test_start_url_is_a_web_address(url: str | None, expected: str) -> None:
    assert cp.safe_start_url(url) == expected


def test_handoff_page_is_titled_with_the_token_and_forwards() -> None:
    token = cp.new_token()
    assert cp.is_token(token)
    url = cp.handoff_url(token, "https://example.com/?a=1&b=</script>")
    assert url.startswith("data:text/html;charset=utf-8,")
    html = unquote(url.split(",", 1)[1])
    assert f"<title>{token}</title>" in html
    assert "location.replace" in html
    # The address cannot close the script tag it is written into.
    assert "</script>\"" not in html
    assert "\\u003c/script>" in html


def test_handoff_rejects_a_bad_token() -> None:
    with pytest.raises(ValueError):
        cp.handoff_url("<title>", "https://example.com")


def test_panel_rect_scales_and_offsets() -> None:
    rect = {"x": 100.4, "y": 50.0, "width": 300.0, "height": 200.5}
    assert cp.panel_to_client_rect(rect, 1.5, (8, 0)) == (159, 75, 450, 301)


def test_touching_panels_stay_touching() -> None:
    left = cp.panel_to_client_rect({"x": 0, "y": 0, "width": 100.3, "height": 10}, 1.25, (0, 0))
    right = cp.panel_to_client_rect({"x": 100.3, "y": 0, "width": 50, "height": 10}, 1.25, (0, 0))
    assert left[0] + left[2] == right[0]


def test_panel_rect_never_negative() -> None:
    rect = {"x": 5, "y": 5, "width": -3, "height": 0}
    assert cp.panel_to_client_rect(rect, 0, (0, 0))[2:] == (0, 0)
