"""A variable written as ``DODAIOS_<NAME>`` reaches the reader of ``JARVIS_<NAME>``.

``jarvis.core.env_prefix`` moves every new-prefix variable to the name the code
reads, once per process, before any reader runs. These tests hold the
precedence, the reason the new name is moved rather than mirrored (scrubbing
and overrides keep working), the copy the frozen runtime hook carries, and
what a real child process sees.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import jarvis.core.env_prefix as env_prefix
from jarvis.core import config as core_config
from jarvis.core.env_prefix import accepted_names, adopt_environment, old_name_of
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

_ROOT = Path(__file__).resolve().parents[3]
_HOOK_PATH = _ROOT / "packaging" / "pyinstaller_rthook_frozen.py"

# Some tests run the adoption on the real environment, as the package does.
pytestmark = pytest.mark.usefixtures("prefixed_environment_restored")


# ---------------------------------------------------------------------------
# Both prefixes resolve
# ---------------------------------------------------------------------------


def test_a_new_name_reaches_the_reader_of_the_old_name() -> None:
    environ = {"DODAIOS_DATA_DIR": "/srv/data", "PATH": "/bin"}

    assert adopt_environment(environ) == ()

    assert environ == {"JARVIS_DATA_DIR": "/srv/data", "PATH": "/bin"}


def test_an_old_name_keeps_working_untouched() -> None:
    environ = {"JARVIS_BIND_HOST": "127.0.0.1", "JARVIS__BRAIN__PRIMARY": "gemini"}
    before = dict(environ)

    assert adopt_environment(environ) == ()

    assert environ == before


def test_a_nested_config_override_works_under_the_new_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Set (not deleted), so monkeypatch takes back what the adoption writes.
    monkeypatch.setenv("JARVIS__BRAIN__PRIMARY", "")
    monkeypatch.setenv("DODAIOS__BRAIN__PRIMARY", "openrouter")

    adopt_environment()

    # The reader is untouched: it still scans for the JARVIS__ spelling.
    assert core_config._apply_env_overrides({})["brain"]["primary"] == "openrouter"
    assert "DODAIOS__BRAIN__PRIMARY" not in os.environ


def test_the_control_cli_prefix_is_adopted_too() -> None:
    environ = {"DODAIOSCTL_BASE_URL": "http://127.0.0.1:47821", "JARVISCTL_CACHE_HOME": "/c"}

    assert adopt_environment(environ) == ()

    assert environ == {
        "JARVISCTL_BASE_URL": "http://127.0.0.1:47821",
        "JARVISCTL_CACHE_HOME": "/c",
    }


def test_unrelated_and_bare_prefix_names_are_left_alone() -> None:
    environ = {
        "DODAIOS_": "bare",
        "DODAIOSCTL_": "bare",
        "MY_DODAIOS_VAR": "1",
        "dodaios_lower": "2",
        "DODAIOSX_OTHER": "3",
    }
    before = dict(environ)

    assert adopt_environment(environ) == ()

    assert environ == before


@pytest.mark.parametrize(
    ("new_name", "expected"),
    [
        ("DODAIOS_CONFIG", "JARVIS_CONFIG"),
        ("DODAIOS__TTS__PROVIDER", "JARVIS__TTS__PROVIDER"),
        ("DODAIOSCTL_CONTROL_KEY", "JARVISCTL_CONTROL_KEY"),
        ("JARVIS_CONFIG", None),
        ("DODAIOS_", None),
        ("PATH", None),
    ],
)
def test_the_name_the_code_reads(new_name: str, expected: str | None) -> None:
    assert old_name_of(new_name) == expected


def test_every_spelling_of_a_name_the_code_reads() -> None:
    assert accepted_names("JARVIS_ADMIN_HMAC") == ("DODAIOS_ADMIN_HMAC", "JARVIS_ADMIN_HMAC")
    assert accepted_names("JARVISCTL_BASE_URL") == ("DODAIOSCTL_BASE_URL", "JARVISCTL_BASE_URL")
    assert accepted_names("GROQ_API_KEY") == ("GROQ_API_KEY",)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_the_new_name_wins_when_both_are_set_differently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    environ = {"JARVIS_PERSONA": "old-value", "DODAIOS_PERSONA": "new-value"}

    with caplog.at_level(logging.WARNING, logger="jarvis.core.env_prefix"):
        clashes = adopt_environment(environ)

    assert clashes == ("DODAIOS_PERSONA",)
    assert environ == {"JARVIS_PERSONA": "new-value"}
    # One line, naming both spellings and never a value.
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "DODAIOS_PERSONA" in message and "JARVIS_PERSONA" in message
    assert "value" not in message.replace("different values", "")


def test_equal_values_are_no_clash(caplog: pytest.LogCaptureFixture) -> None:
    environ = {"JARVIS_DEBUG": "1", "DODAIOS_DEBUG": "1"}

    with caplog.at_level(logging.WARNING, logger="jarvis.core.env_prefix"):
        assert adopt_environment(environ) == ()

    assert environ == {"JARVIS_DEBUG": "1"}
    assert caplog.records == []


def test_a_blank_new_name_does_not_override_a_value() -> None:
    environ = {"JARVIS_CONFIG": "/etc/app.toml", "DODAIOS_CONFIG": ""}

    assert adopt_environment(environ) == ()

    assert environ == {"JARVIS_CONFIG": "/etc/app.toml"}


def test_a_new_name_replaces_a_blank_old_one_without_a_clash() -> None:
    environ = {"JARVIS_CONFIG": "", "DODAIOS_CONFIG": "/etc/app.toml"}

    assert adopt_environment(environ) == ()

    assert environ == {"JARVIS_CONFIG": "/etc/app.toml"}


def test_a_blank_new_name_alone_is_still_carried_over() -> None:
    environ = {"DODAIOS_VOICE": ""}

    assert adopt_environment(environ) == ()

    assert environ == {"JARVIS_VOICE": ""}


def test_a_second_pass_changes_nothing() -> None:
    environ = {"JARVIS_A": "1", "DODAIOS_B": "2", "JARVIS_C": "x", "DODAIOS_C": "y"}
    assert adopt_environment(environ) == ("DODAIOS_C",)
    settled = dict(environ)

    assert adopt_environment(environ) == ()
    assert environ == settled == {"JARVIS_A": "1", "JARVIS_B": "2", "JARVIS_C": "y"}


# ---------------------------------------------------------------------------
# Why the new name is moved: what the app does afterwards keeps working
# ---------------------------------------------------------------------------


def test_a_variable_scrubbed_by_its_old_name_is_gone_from_the_child() -> None:
    # Code that starts an external tool drops credentials by the name the code
    # reads. Had the new spelling stayed beside it, the value would pass.
    environ = {"DODAIOS_CONTROL_API_KEY": "the-value", "DODAIOSCTL_CONTROL_KEY": "the-value"}
    adopt_environment(environ)

    child = dict(environ)
    for name in ("JARVIS_CONTROL_API_KEY", "JARVISCTL_CONTROL_KEY"):
        child.pop(name, None)

    assert "the-value" not in child.values()


def test_an_override_set_for_a_child_is_what_the_child_reads() -> None:
    # The app points one worker at its own directory. The child must read
    # that, not the value the person originally set under the new name.
    environ = {"DODAIOS_DATA_DIR": "/home/u/data"}
    adopt_environment(environ)

    child = {**environ, "JARVIS_DATA_DIR": "/srv/worker"}

    assert adopt_environment(child) == ()
    assert child == {"JARVIS_DATA_DIR": "/srv/worker"}


def test_a_marker_removed_before_a_restart_does_not_return() -> None:
    environ = {"DODAIOS_BRANDED_LAUNCH": "1", "JARVIS_DEBUG": "1"}
    adopt_environment(environ)

    child = dict(environ)
    del child["JARVIS_BRANDED_LAUNCH"]

    adopt_environment(child)
    assert child == {"JARVIS_DEBUG": "1"}


# ---------------------------------------------------------------------------
# The package adopts the environment for every entry point
# ---------------------------------------------------------------------------

_CHILD_REPORT = (
    "import json, os, jarvis; "
    "print(json.dumps({k: v for k, v in os.environ.items() "
    "if k.startswith(('JARVIS', 'DODAIOS'))}))"
)
_GRANDCHILD_REPORT = (
    "import json, os, subprocess, sys, jarvis; "
    "from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS as F; "
    "os.environ['JARVIS_PRIMARY_INSTANCE'] = '0'; "
    "r = subprocess.run([sys.executable, '-c', sys.argv[1]], capture_output=True, text=True, "
    "encoding='utf-8', creationflags=F); "
    "sys.stderr.write(r.stderr); print(r.stdout.strip().splitlines()[-1])"
)


def _run_child(environ: dict[str, str], code: str, *args: str) -> dict[str, str]:
    base = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("JARVIS", "DODAIOS"))
    }
    base["PYTHONPATH"] = str(_ROOT)
    result = subprocess.run(  # noqa: S603 - the interpreter running this test
        [sys.executable, "-c", code, *args],
        env={**base, **environ},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_importing_the_package_adopts_the_environment_of_a_real_process() -> None:
    seen = _run_child(
        {
            "DODAIOS_DATA_DIR": "new-only",
            "JARVIS_BIND_HOST": "old-only",
            "DODAIOS__UI__LANGUAGE": "en",
            "DODAIOSCTL_BASE_URL": "http://127.0.0.1:1",
        },
        _CHILD_REPORT,
    )

    assert seen == {
        "JARVIS_DATA_DIR": "new-only",
        "JARVIS_BIND_HOST": "old-only",
        "JARVIS__UI__LANGUAGE": "en",
        "JARVISCTL_BASE_URL": "http://127.0.0.1:1",
    }


def test_a_grandchild_reads_what_its_parent_set_after_the_adoption() -> None:
    # The person starts the app with the new name; the app then sets the
    # variable itself (as the launcher does) and starts a helper.
    seen = _run_child(
        {"DODAIOS_PRIMARY_INSTANCE": "1", "DODAIOS_DEBUG": "1"},
        _GRANDCHILD_REPORT,
        _CHILD_REPORT,
    )

    assert seen == {"JARVIS_PRIMARY_INSTANCE": "0", "JARVIS_DEBUG": "1"}


def test_the_module_needs_nothing_but_the_standard_library() -> None:
    tree = ast.parse((_ROOT / "jarvis" / "core" / "env_prefix.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "logging", "os"}


def test_the_package_runs_the_adoption_before_anything_else() -> None:
    tree = ast.parse((_ROOT / "jarvis" / "__init__.py").read_text(encoding="utf-8"))
    calls = [
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]
    assert calls and calls[0] == "_adopt_environment"


# ---------------------------------------------------------------------------
# The frozen runtime hook carries an identical copy
# ---------------------------------------------------------------------------


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("env_prefix_rthook_frozen", _HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # a no-op outside a frozen build
    return module


def _function_node(path: Path, name: str) -> ast.FunctionDef:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} defines no {name}")


def test_the_hook_copy_of_the_adoption_is_identical() -> None:
    package = _function_node(_ROOT / "jarvis" / "core" / "env_prefix.py", "_adopt")
    hook = _function_node(_HOOK_PATH, "_adopt")

    assert ast.dump(hook) == ast.dump(package), (
        "packaging/pyinstaller_rthook_frozen.py::_adopt must be a verbatim copy of "
        "jarvis/core/env_prefix.py::_adopt"
    )


def test_the_hook_restates_the_prefixes() -> None:
    assert _load_hook()._PREFIXES == env_prefix._PREFIXES


def _frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    hook = _load_hook()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    return hook


def test_the_hook_honours_an_override_under_the_new_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _frozen(tmp_path, monkeypatch)
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("JARVIS_CONFIG", "")
    monkeypatch.setenv("JARVIS_DATA_DIR", "")
    monkeypatch.setenv("DODAIOS_CONFIG", str(scratch / "app.toml"))
    monkeypatch.setenv("DODAIOS_DATA_DIR", str(scratch / "data"))

    hook._apply()

    # The hook did not point them at the per-user directory: the override won.
    assert os.environ["JARVIS_CONFIG"] == str(scratch / "app.toml")
    assert os.environ["JARVIS_DATA_DIR"] == str(scratch / "data")
    assert "DODAIOS_CONFIG" not in os.environ and "DODAIOS_DATA_DIR" not in os.environ
    assert not (tmp_path / "local").exists()


def test_the_hook_names_a_clash_without_its_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _frozen(tmp_path, monkeypatch)
    monkeypatch.setenv("JARVIS_CONFIG", str(tmp_path / "old-value.toml"))
    monkeypatch.setenv("DODAIOS_CONFIG", str(tmp_path / "new-value.toml"))
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))

    hook._apply()

    assert os.environ["JARVIS_CONFIG"] == str(tmp_path / "new-value.toml")
    warning = capsys.readouterr().err
    assert "DODAIOS_CONFIG" in warning
    assert "old-value" not in warning and "new-value" not in warning
