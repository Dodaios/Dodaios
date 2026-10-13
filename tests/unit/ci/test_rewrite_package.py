"""The package rename codemod, run on a small real git repository.

The file is full of the OLD package name on purpose: it is the codemod's input
and expectation, so the codemod itself never rewrites it (``FROZEN_FILES``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.rename import rewrite_package as codemod

OLD, NEW = "jarvis", "dodaios"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_MAIN = '''"""Start the app."""
import sys


def main() -> int:
    print("ran", __spec__.name if __spec__ else None, "as", __name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_PYPROJECT = """[project]
name = "personal-jarvis"

[project.scripts]
jarvis = "jarvis.__main__:main"
personal-jarvis = "jarvis.__main__:main"
jarvisctl = "jarvis.cli_ctl.__main__:main"

[project.entry-points."jarvis.brain"]
openai = "jarvis.plugins.brain.openai:OpenAIBrain"

[project.entry-points."jarvis.tool"]
click = "jarvis.plugins.tool.click:ClickTool"

[tool.setuptools.packages.find]
include = ["jarvis*", "conductor*"]

[tool.setuptools.package-data]
conductor = ["core/schema.sql"]
jarvis = [
    "ui/web/dist/**/*",
    # read by jarvis/brain/persona.py
    "brain/PERSONA.md",
]

[tool.setuptools.data-files]
"share/personal-jarvis/docs" = ["docs/**/*.md"]
"""

_WORKFLOW = """on:
  pull_request:
    paths:
      - "jarvis/appshot/**"
      - "jarvis/ui/web/appshot_routes.py"
      - "tests/unit/appshot/**"
env:
  JARVIS_CONFIG: /app/data/jarvis.toml
jobs:
  lint:
    steps:
      - run: python -m ruff check jarvis/
      - run: python -m mypy jarvis tests
      - run: python -c "import jarvis.cli_ctl.__main__"
      - run: python -m jarvis.cli_ctl --help
      - run: pytest --cov=jarvis tests
        working-directory: jarvis/ui/web/frontend
      - run: echo "${{ hashFiles('jarvis/agent_runtimes/runtime-versions.json') }}"
      - run: jarvis serve --headless
"""

_DOCKERFILE = """WORKDIR /build/jarvis/ui/web/frontend
COPY jarvis/ui/web/frontend/package.json ./
COPY jarvis ./jarvis
COPY --from=web /build/jarvis/ui/web/dist ./jarvis/ui/web/dist
RUN useradd --system jarvis && chown -R jarvis:jarvis /app/data
USER jarvis
ENV JARVIS_CONFIG=/app/data/jarvis.toml
# docker run -v jarvis-data:/app/data personal-jarvis
CMD ["python", "-m", "jarvis.ui.web.launcher", "--headless"]
"""

_SPEC = """FRONTEND_DIST = PROJECT_ROOT / "jarvis" / "ui" / "web" / "dist"
_package_root = PROJECT_ROOT / "jarvis"
CLI_EXE_NAME = "jarvis"
MACOS_BUNDLE_IDENTIFIER = "ai.personaljarvis.desktop"
datas = [(str(PROJECT_ROOT / "jarvis.toml"), ".")]
datas.append((str(PROJECT_ROOT / "jarvis/society/x.py"), "jarvis/society"))
hiddenimports = collect_submodules("jarvis.plugins")
ENTRY = ["jarvis/__main__.py"]
print("[jarvis.spec] icon is missing")
"""

_TEST_MODULE = """import importlib
import logging
import sys

import jarvis
from jarvis.core import branding
from jarvis.core.config import load


def test_it(monkeypatch, caplog):
    monkeypatch.setattr("jarvis.core.config.load", lambda: None)
    monkeypatch.setitem(sys.modules, "jarvis.realtime", None)
    module = importlib.import_module("jarvis.ui.web.launcher")
    runtime = sys.modules.get("jarvis.society.runtime")
    with caplog.at_level(logging.INFO, logger="jarvis.core.config"):
        logging.getLogger("jarvis").info("x")
    argv = [sys.executable, "-m", "jarvis", "--headless"]
    other = [sys.executable, "-m", "jarvis.ui.relauncher", "1", "."]
    root = Path(jarvis.__file__).parent
    version = jarvis.__version__
    session = make(surface="jarvis", opened_by="jarvis")
    for surface in ("jarvis", "agents"):
        pass
"""

_BUILD_PS1 = """$FrontendDist = Join-Path $RepoRoot "jarvis\\ui\\web\\dist"
$InitFile = Join-Path $RepoRoot "jarvis\\__init__.py"
if (-not (Test-Path $SpecFile)) { Stop-WithError "jarvis.spec not found" }
$IconFile = Join-Path $RepoRoot "assets\\icons\\jarvis.ico"
"""

_GUIDE = """# Guide

The package lives in `jarvis/` (see `jarvis/core/config.py:12` and
`jarvis/{core,ui}/`). Import it with `from jarvis.core import branding`; plugins
import nothing from `jarvis.*`. The removed module `jarvis/awareness/probe.py`
is gone. Start it with `jarvis serve` or `python -m jarvis`; settings are in
`jarvis.toml`, data in `~/.jarvis/` and `data/jarvis.db`.
Hey Jarvis, what is on today?
"""

_WEB_SOURCE = """// Kept in step with jarvis.ui.web.launcher (jarvis/ui/web/launcher.py).
const STOP_KEY = "jarvis.ui.walkStop";
const GROUPS = [{ group: "jarvis.brain" }];
const own = /^jarvis\\//i.test(name) ? name.slice("jarvis/".length) : null;
// "jarvis/gmail" is the Gmail plugin.
"""

_HISTORY = "- moved `jarvis/core/old.py`; run `python -m jarvis.ui.web.launcher`\n"

FILES: dict[str, str] = {
    "jarvis/__init__.py": '"""The package."""\n\n__version__ = "1.2.3"\n',
    "jarvis/__main__.py": _MAIN,
    "jarvis/core/__init__.py": "",
    "jarvis/core/branding.py": 'NAME = "Thing"\nSTATE: list[str] = []\n',
    "jarvis/core/config.py": (
        "from jarvis.core.branding import NAME\n\n\ndef load() -> str:\n    return NAME\n"
    ),
    "jarvis/brain/__init__.py": "from jarvis.core import branding as branding\n",
    "jarvis/plugins/__init__.py": "",
    "jarvis/appshot/__init__.py": "",
    "jarvis/agent_runtimes/runtime-versions.json": "{}\n",
    "jarvis/cli_ctl/__init__.py": "",
    "jarvis/cli_ctl/__main__.py": _MAIN,
    "jarvis/realtime/__init__.py": "",
    "jarvis/society/__init__.py": "",
    "jarvis/society/x.py": "",
    "jarvis/ui/__init__.py": "",
    "jarvis/ui/relauncher.py": _MAIN,
    "jarvis/ui/web/__init__.py": "",
    "jarvis/ui/web/launcher.py": _MAIN,
    "jarvis/ui/web/dist/index.html": '<script src="jarvis/ui/web/x.js">jarvis.core.y</script>\n',
    "jarvis/ui/web/frontend/src/app.ts": _WEB_SOURCE,
    "jarvis/ui/web/frontend/src/i18n/locales/en.json": (
        '{"hint": "Run python -m jarvis.ui.web.launcher, see jarvis/core/config.py"}\n'
    ),
    "jarvis/mcp/__init__.py": "",
    "jarvis/mcp/server.py": _MAIN,
    "jarvis/mcp/agents/__init__.py": "",
    "jarvis/mcp/agents/bridge.py": _MAIN,
    "pyproject.toml": _PYPROJECT,
    "jarvis.spec": _SPEC,
    "jarvis.toml.example": "# settings\n[brain]\n",
    "Dockerfile": _DOCKERFILE,
    ".github/workflows/ci.yml": _WORKFLOW,
    "scripts/ci/german-allowlist.txt": "jarvis/brain/__init__.py\njarvis/core/config.py\n",
    "packaging/build.ps1": _BUILD_PS1,
    ".gitignore": "/jarvis.toml\njarvis/ui/web/frontend/node_modules/\n.jarvis-managed-install\n",
    "docs/guide.md": _GUIDE,
    "CHANGELOG.md": _HISTORY,
    "docs/BUGS.md": _HISTORY,
    "docs/supply-chain/wave3.md": _HISTORY,
    "docs/superpowers/plans/plan.md": _HISTORY,
    "tests/test_core.py": _TEST_MODULE,
    "legacy_samples.txt": "\n".join(
        sample for entry in codemod.LEGACY_IDENTIFIERS for sample in entry.samples
    )
    + "\n",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        creationflags=_NO_WINDOW,
    ).stdout


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    _write(root, FILES)
    _git(root, "add", "-f", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _read(repo: Path, name: str) -> str:
    return (repo / name).read_text(encoding="utf-8")


def _tracked(repo: Path) -> set[str]:
    return set(_git(repo, "ls-files").split())


def _rewriter() -> codemod.Rewriter:
    """A rewriter that knows the small package above."""
    paths = [name[len(OLD) + 1 :] for name in FILES if name.startswith(OLD + "/")]
    return codemod.Rewriter(OLD, NEW, paths, groups=["brain", "tool"])


def _rewritten(text: str, path: str = "notes/sample.py") -> str:
    return _rewriter().transform(path, text.encode("utf-8")).decode("utf-8")


# --------------------------------------------------------------------------- the run


def test_dry_run_reports_and_changes_nothing(repo, capsys):
    before = _git(repo, "status", "--porcelain")
    assert codemod.main(["--from", OLD, "--to", NEW, "--root", str(repo), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "move     jarvis/__init__.py -> dodaios/__init__.py" in out
    assert "rewrite  pyproject.toml:" in out
    assert "file(s) to move" in out and "ambiguous hit(s)" in out
    assert _git(repo, "status", "--porcelain") == before
    assert not (repo / NEW).exists()
    assert _read(repo, "jarvis/core/config.py") == FILES["jarvis/core/config.py"]


def test_a_run_moves_the_package_and_stages_exactly_its_work(repo):
    (repo / "notes.txt").write_text("someone else's untracked work\n", encoding="utf-8")
    report = codemod.apply(repo, OLD, NEW)

    assert not report.blocked
    tracked = _tracked(repo)
    package_files = {name for name in FILES if name.startswith("jarvis/")}
    assert {NEW + name[len(OLD) :] for name in package_files} <= tracked
    # Only the compatibility package is left under the old name.
    assert {name for name in tracked if name.startswith("jarvis/")} == {"jarvis/__init__.py"}
    assert codemod.STUB_MARKER in _read(repo, "jarvis/__init__.py")
    # The frontend source and the built bundle moved with the package.
    assert "dodaios/ui/web/frontend/src/app.ts" in tracked
    assert "dodaios/ui/web/dist/index.html" in tracked
    # Everything the run wrote is staged; the stranger's file is not.
    assert _git(repo, "diff", "--name-only") == ""
    assert "notes.txt" not in _git(repo, "diff", "--cached", "--name-only")
    renames = _git(repo, "diff", "--cached", "--name-status", "-M")
    assert "jarvis/core/branding.py\tdodaios/core/branding.py" in renames


def test_imports_and_module_paths_are_rewritten(repo):
    codemod.apply(repo, OLD, NEW)

    assert _read(repo, "dodaios/core/config.py").startswith("from dodaios.core.branding import")
    assert (
        _read(repo, "dodaios/brain/__init__.py")
        == "from dodaios.core import branding as branding\n"
    )
    test_module = _read(repo, "tests/test_core.py")
    for expected in (
        "import dodaios\n",
        "from dodaios.core import branding",
        "from dodaios.core.config import load",
        'monkeypatch.setattr("dodaios.core.config.load"',
        'monkeypatch.setitem(sys.modules, "dodaios.realtime", None)',
        'importlib.import_module("dodaios.ui.web.launcher")',
        'sys.modules.get("dodaios.society.runtime")',
        'logger="dodaios.core.config"',
        'logging.getLogger("dodaios")',
        '"-m", "dodaios", "--headless"',
        '"-m", "dodaios.ui.relauncher"',
        "Path(dodaios.__file__)",
        "dodaios.__version__",
        # Names that only look like the package stay.
        'make(surface="jarvis", opened_by="jarvis")',
        'for surface in ("jarvis", "agents")',
    ):
        assert expected in test_module, expected
    assert "jarvis." not in test_module


def test_pyproject_moves_targets_and_keeps_command_and_group_names(repo):
    codemod.apply(repo, OLD, NEW)
    text = _read(repo, "pyproject.toml")

    assert 'name = "personal-jarvis"' in text
    assert 'jarvis = "dodaios.__main__:main"' in text
    assert 'personal-jarvis = "dodaios.__main__:main"' in text
    assert 'jarvisctl = "dodaios.cli_ctl.__main__:main"' in text
    assert '[project.entry-points."jarvis.brain"]' in text
    assert '[project.entry-points."jarvis.tool"]' in text
    assert 'openai = "dodaios.plugins.brain.openai:OpenAIBrain"' in text
    assert 'click = "dodaios.plugins.tool.click:ClickTool"' in text
    # Both packages ship: the real one and the compatibility one.
    assert 'include = ["dodaios*", "jarvis*", "conductor*"]' in text
    assert "\ndodaios = [\n" in text and "\njarvis = [\n" not in text
    assert "# read by dodaios/brain/persona.py" in text
    assert '"share/personal-jarvis/docs"' in text


def test_paths_are_rewritten_in_workflows_packaging_and_allowlists(repo):
    codemod.apply(repo, OLD, NEW)

    workflow = _read(repo, ".github/workflows/ci.yml")
    for expected in (
        '- "dodaios/appshot/**"',
        '- "dodaios/ui/web/appshot_routes.py"',
        "ruff check dodaios/",
        "mypy dodaios tests",
        'python -c "import dodaios.cli_ctl.__main__"',
        "python -m dodaios.cli_ctl --help",
        "--cov=dodaios tests",
        "working-directory: dodaios/ui/web/frontend",
        "hashFiles('dodaios/agent_runtimes/runtime-versions.json')",
        "JARVIS_CONFIG: /app/data/jarvis.toml",
        "run: jarvis serve --headless",
    ):
        assert expected in workflow, expected
    assert _read(repo, "scripts/ci/german-allowlist.txt") == (
        "dodaios/brain/__init__.py\ndodaios/core/config.py\n"
    )
    assert _read(repo, ".gitignore") == (
        "/jarvis.toml\ndodaios/ui/web/frontend/node_modules/\n.jarvis-managed-install\n"
    )
    assert _read(repo, "packaging/build.ps1") == _BUILD_PS1.replace(
        '"jarvis\\ui', '"dodaios\\ui'
    ).replace('"jarvis\\__init__', '"dodaios\\__init__')

    spec = _read(repo, "jarvis.spec")  # the file keeps its name, its content moves
    for expected in (
        'PROJECT_ROOT / "dodaios" / "ui" / "web" / "dist"',
        '_package_root = PROJECT_ROOT / "dodaios"',
        'CLI_EXE_NAME = "jarvis"',
        '"ai.personaljarvis.desktop"',
        'PROJECT_ROOT / "jarvis.toml"',
        '"dodaios/society/x.py"), "dodaios/society")',
        'collect_submodules("dodaios.plugins")',
        '["dodaios/__main__.py"]',
        "[jarvis.spec] icon is missing",
    ):
        assert expected in spec, expected

    docker = _read(repo, "Dockerfile")
    assert "WORKDIR /build/dodaios/ui/web/frontend" in docker
    assert "COPY dodaios ./dodaios\nCOPY jarvis ./jarvis\n" in docker
    assert "COPY --from=web /build/dodaios/ui/web/dist ./dodaios/ui/web/dist" in docker
    assert "useradd --system jarvis && chown -R jarvis:jarvis /app/data" in docker
    assert "-v jarvis-data:/app/data personal-jarvis" in docker
    assert '"-m", "dodaios.ui.web.launcher"' in docker


def test_documents_follow_the_package_and_keep_names(repo):
    codemod.apply(repo, OLD, NEW)
    guide = _read(repo, "docs/guide.md")

    for expected in (
        "lives in `dodaios/` (see `dodaios/core/config.py:12`",
        "`dodaios/{core,ui}/`",
        "`from dodaios.core import branding`",
        "nothing from `dodaios.*`",
        "`dodaios/awareness/probe.py`",  # a removed module is still a path of the package
        "`jarvis serve` or `python -m dodaios`",
        "`jarvis.toml`, data in `~/.jarvis/` and `data/jarvis.db`",
        "Hey Jarvis, what is on today?",
    ):
        assert expected in guide, expected


def test_web_sources_keep_storage_keys_and_tool_prefixes(repo):
    codemod.apply(repo, OLD, NEW)
    source = _read(repo, "dodaios/ui/web/frontend/src/app.ts")

    assert "dodaios.ui.web.launcher (dodaios/ui/web/launcher.py)" in source
    assert 'const STOP_KEY = "jarvis.ui.walkStop";' in source
    assert '{ group: "jarvis.brain" }' in source
    assert 'name.slice("jarvis/".length)' in source
    assert '"jarvis/gmail" is the Gmail plugin' in source


# --------------------------------------------------------------------------- what stays


@pytest.mark.parametrize(
    "entry", codemod.LEGACY_IDENTIFIERS, ids=[entry.name for entry in codemod.LEGACY_IDENTIFIERS]
)
def test_every_legacy_identifier_survives(entry):
    assert entry.reason and entry.samples
    for sample in entry.samples:
        for path in ("notes/sample.py", "notes/sample.md", "notes/sample.toml", "notes/run.sh"):
            assert _rewritten(sample, path) == sample, (entry.name, path, sample)


def test_legacy_identifiers_survive_a_whole_run(repo):
    codemod.apply(repo, OLD, NEW)
    assert _read(repo, "legacy_samples.txt") == FILES["legacy_samples.txt"]
    assert _read(repo, "jarvis.toml.example") == FILES["jarvis.toml.example"]
    assert "jarvis.spec" in _tracked(repo) and "jarvis.toml.example" in _tracked(repo)


@pytest.mark.parametrize(
    "frozen", codemod.FROZEN_FILES, ids=[frozen.glob for frozen in codemod.FROZEN_FILES]
)
def test_every_frozen_file_keeps_its_content(frozen):
    assert frozen.reason
    text = "see jarvis/core/config.py and `from jarvis.core import branding`\n"
    assert _rewritten(text) != text  # the same words anywhere else are rewritten
    for package in (OLD, NEW):
        path = frozen.glob.replace("{pkg}", package).replace("**/", "web/").replace("**", "a/b.md")
        assert _rewritten(text, path) == text, path


def test_history_and_generated_files_are_moved_but_not_rewritten(repo):
    codemod.apply(repo, OLD, NEW)
    for name in ("CHANGELOG.md", "docs/BUGS.md", "docs/supply-chain/wave3.md"):
        assert _read(repo, name) == _HISTORY, name
    assert _read(repo, "docs/superpowers/plans/plan.md") == _HISTORY
    assert _read(repo, "dodaios/ui/web/dist/index.html") == FILES["jarvis/ui/web/dist/index.html"]
    locale = "ui/web/frontend/src/i18n/locales/en.json"
    assert _read(repo, f"dodaios/{locale}") == FILES[f"jarvis/{locale}"]


def test_a_line_with_the_pragma_is_left_alone():
    text = (
        "from jarvis.core import branding  # rename-keep: read by an old updater\n"
        "from jarvis.core import config\n"
    )
    assert _rewritten(text) == text.replace(
        "from jarvis.core import config", "from dodaios.core import config"
    )


@pytest.mark.parametrize(
    "text",
    [
        'key = "jarvis"',
        "Ask Jarvis, or type `jarvis update`.",
        'COOKIE = "jarvis_session"',
        "mcp_servers.jarvis.required=true",
        "extras.jarvis_figure",
        'home / ".config" / "jarvis" / "agent.env"',
        'link = bin_dir / "jarvis"',
        'service_account_path = "~/.config/jarvis/vertex-sa.json"',
        "ExecStart=/home/jarvis/jarvis-venv/bin/jarvis serve",
        'log = logging.getLogger("jarvis.wake.vosk")',  # a logger name, not a module
        'PLUGIN_GROUP = "jarvis.brain"',
        'entry_points(group="jarvis.tool")',
        "jarvis.toml jarvis.db jarvis.lock jarvis.spec jarvis.ico",
        "hauptjarvis subjarvis_worker personaljarvis.ai",
        r'pattern = re.compile(r"\bjarvis\b")',
    ],
)
def test_names_that_only_look_like_the_package_are_kept(text):
    assert _rewritten(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("import jarvis", "import dodaios"),
        ("from jarvis import __version__", "from dodaios import __version__"),
        ("import jarvis.brain", "import dodaios.brain"),
        ("from jarvis.brain import router", "from dodaios.brain import router"),
        ("x = jarvis.core.config.load()", "x = dodaios.core.config.load()"),
        ('"-m", "jarvis.mcp.server"', '"-m", "dodaios.mcp.server"'),
        ("python -m jarvis.mcp.agents.bridge", "python -m dodaios.mcp.agents.bridge"),
        ('find_spec("jarvis")', 'find_spec("dodaios")'),
        ('patch("jarvis.brain")', 'patch("dodaios.brain")'),
        ('"jarvis.brain:Router"', '"dodaios.brain:Router"'),
        (r're.compile(r"^from\s+jarvis\.core\b")', r're.compile(r"^from\s+dodaios\.core\b")'),
        ('root / "jarvis" / "core"', 'root / "dodaios" / "core"'),
        ('os.path.join(root, "jarvis", "ui")', 'os.path.join(root, "dodaios", "ui")'),
        ('(tmp_path / "jarvis").mkdir()', '(tmp_path / "dodaios").mkdir()'),
        ('path.startswith("jarvis/")', 'path.startswith("dodaios/")'),
        ("git add jarvis/core/config.py", "git add dodaios/core/config.py"),
        ("site-packages/jarvis/core/x.py", "site-packages/dodaios/core/x.py"),
        (
            "diff --git a/jarvis/foo.py b/jarvis/foo.py",
            "diff --git a/dodaios/foo.py b/dodaios/foo.py",
        ),
        ('Join-Path $Root "jarvis\\ui\\web"', 'Join-Path $Root "dodaios\\ui\\web"'),
        ('_CODE_ROOTS = ("jarvis", "scripts")', '_CODE_ROOTS = ("dodaios", "scripts")'),
        ('for root in ("jarvis", "tests"):', 'for root in ("dodaios", "tests"):'),
        ('argv = [\n    "-m",\n    "jarvis",\n]', 'argv = [\n    "-m",\n    "dodaios",\n]'),
        (
            'import jarvis\n\nmonkeypatch.setattr(jarvis, "accounts", fake)\n',
            'import dodaios\n\nmonkeypatch.setattr(dodaios, "accounts", fake)\n',
        ),
    ],
)
def test_references_to_the_package_are_rewritten(text, expected):
    assert _rewritten(text) == expected


# --------------------------------------------------------------------------- ambiguous


def test_undecidable_hits_are_reported_with_their_line_and_left_alone(repo):
    notes = (
        "# notes\n"
        'FORBIDDEN = ("fastapi", "jarvis.brain", "jarvis.core.config")\n'
        'branch = f"jarvis/{slug}"\n'
        'model = "jarvis/gpt-5.2"\n'
    )
    _write(repo, {"notes.py": notes})
    _git(repo, "add", "notes.py")

    report, contents = codemod.plan(repo, OLD, NEW)

    found = {(hit.path, hit.line): hit.reason for hit in report.ambiguous}
    assert ("notes.py", 2) in found and "plugin group or module" in found[("notes.py", 2)]
    assert ("notes.py", 3) in found and "placeholder" in found[("notes.py", 3)]
    assert ("notes.py", 4) in found and "not in the package" in found[("notes.py", 4)]
    rewritten = contents["notes.py"].decode("utf-8")
    # The decidable half of line 2 moved; the undecidable names are untouched.
    assert '("fastapi", "jarvis.brain", "dodaios.core.config")' in rewritten
    assert 'f"jarvis/{slug}"' in rewritten and '"jarvis/gpt-5.2"' in rewritten
    rendered = report.ambiguous[0].render()
    assert rendered.startswith("notes.py:2:") or "notes.py:" in rendered


@pytest.mark.parametrize(
    "text",
    [
        'if any(name.startswith("jarvis.") for name in sys.modules):\n',
        "offenders = [m for m in imported if m.startswith('jarvis.')]\n",
        'if name.startswith("jarvis"):\n',
        'PREFIXES = ("mcp_jarvis_", "jarvis.")\n',
    ],
)
def test_a_guard_over_module_names_is_reported_and_left_alone(text):
    """Kept silently, a test that forbids imports of the package would go on
    passing while it no longer looks at a single module."""
    data, result = _rewriter().rewrite("tests/test_guard.py", text.encode("utf-8"))

    assert data.decode("utf-8") == text
    assert [hit.line for hit in result.ambiguous] == [1]


def test_the_word_from_before_the_name_is_an_import_only_with_an_import():
    text = (
        "from jarvis import __version__\n"
        'assert sent.startswith("[assignment from jarvis]")\n'
        "task = \"Type the sentence 'hello from jarvis' into it.\"\n"
        'assert "from jarvis" not in generated_code\n'
        'offending = [ln for ln in lines if ln.startswith(("from jarvis", "import jarvis"))]\n'
    )
    data, result = _rewriter().rewrite("tests/test_prose.py", text.encode("utf-8"))

    # The start of an import statement on its own is one a guard tests for;
    # the same two words inside a sentence are prose.
    assert data.decode("utf-8") == (
        "from dodaios import __version__\n"
        'assert sent.startswith("[assignment from jarvis]")\n'
        "task = \"Type the sentence 'hello from jarvis' into it.\"\n"
        'assert "from dodaios" not in generated_code\n'
        'offending = [ln for ln in lines if ln.startswith(("from dodaios", "import dodaios"))]\n'
    )
    assert result.ambiguous == []


def test_a_lookup_in_the_package_data_table_follows_its_key():
    """pyproject's package-data key moves; a test that reads the table by
    that key has to move with it, and no other lookup may."""
    text = (
        'direct = pyproject["tool"]["setuptools"]["package-data"]["jarvis"]\n'
        'patterns = data.get("tool", {}).get("setuptools", {}).get("package-data", {})\n'
        'assert "assets/**/*" in patterns.get("jarvis", [])\n'
        'assert "ui/web/dist/*" in patterns["jarvis"]\n'
        'assert scripts["jarvis"] == entry and surfaces.get("jarvis") is None\n'
    )

    assert _rewritten(text, "tests/test_packaging.py") == (
        'direct = pyproject["tool"]["setuptools"]["package-data"]["dodaios"]\n'
        'patterns = data.get("tool", {}).get("setuptools", {}).get("package-data", {})\n'
        'assert "assets/**/*" in patterns.get("dodaios", [])\n'
        'assert "ui/web/dist/*" in patterns["dodaios"]\n'
        'assert scripts["jarvis"] == entry and surfaces.get("jarvis") is None\n'
    )


def test_a_local_variable_named_like_the_package_is_not_an_import():
    text = "jarvis = roster.lead()\nprint(jarvis.core, jarvis.agent_id)\n"
    rewriter = _rewriter()
    data, result = rewriter.rewrite("notes/sample.py", text.encode("utf-8"))
    assert data.decode("utf-8") == text
    assert [hit.line for hit in result.ambiguous] == [2]


# --------------------------------------------------------------------------- repeatable


@pytest.mark.parametrize("name", sorted(FILES))
def test_a_checkout_with_crlf_line_endings_is_rewritten_the_same(name):
    """The move is made in a working tree and replayed on blobs; both must
    decide alike whatever line endings the checkout has."""
    rewriter = _rewriter()
    lf = FILES[name].encode("utf-8")
    crlf = lf.replace(b"\n", b"\r\n")
    assert rewriter.transform(name, crlf) == rewriter.transform(name, lf).replace(b"\n", b"\r\n")


def test_a_second_run_changes_nothing(repo):
    codemod.apply(repo, OLD, NEW)
    _git(repo, "commit", "-q", "-m", "move")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")

    again = codemod.apply(repo, OLD, NEW)

    assert not again.pending and not again.blocked
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "write-tree") == tree


def test_check_fails_before_the_move_and_passes_after(repo, capsys):
    argv = ["--from", OLD, "--to", NEW, "--root", str(repo), "--check"]
    assert codemod.main(argv) == 1
    assert "check failed" in capsys.readouterr().out

    codemod.apply(repo, OLD, NEW)
    _git(repo, "commit", "-q", "-m", "move")
    assert codemod.main(argv) == 0

    # A reference in the old spelling that slips in later is caught.
    _write(repo, {"late.py": "from jarvis.core import branding\n"})
    _git(repo, "add", "late.py")
    assert codemod.main(argv) == 1
    assert "late.py" in capsys.readouterr().out


def test_a_branch_that_added_a_module_replays_the_same_run(repo):
    _write(
        repo,
        {
            "jarvis/extra/__init__.py": "",
            "jarvis/extra/tool.py": "from jarvis.core import branding\n",
            "docs/extra.md": "See `jarvis/extra/tool.py` and `jarvis.extra.tool`.\n",
        },
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "branch work")

    codemod.apply(repo, OLD, NEW)

    assert _read(repo, "dodaios/extra/tool.py") == "from dodaios.core import branding\n"
    assert _read(repo, "docs/extra.md") == "See `dodaios/extra/tool.py` and `dodaios.extra.tool`.\n"


def test_leftover_caches_under_the_new_name_do_not_stop_the_move(repo):
    """A checkout that has been at the new layout before keeps untracked
    directories there; the move works around them."""
    cache = repo / "dodaios" / "core" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "config.cpython-311.pyc").write_bytes(b"\0cache")

    report = codemod.apply(repo, OLD, NEW)

    assert not report.blocked
    tracked = _tracked(repo)
    assert {name for name in tracked if name.startswith("jarvis/")} == {"jarvis/__init__.py"}
    assert {"dodaios/core/config.py", "dodaios/ui/web/launcher.py"} <= tracked
    assert (cache / "config.cpython-311.pyc").is_file()
    assert _git(repo, "diff", "--name-only") == ""


def test_an_existing_target_blocks_the_run_instead_of_being_overwritten(repo, capsys):
    _write(repo, {"dodaios/core/config.py": "print('already here')\n"})
    assert codemod.main(["--from", OLD, "--to", NEW, "--root", str(repo)]) == 2
    assert "the target already exists" in capsys.readouterr().out
    assert _read(repo, "dodaios/core/config.py") == "print('already here')\n"
    assert (repo / "jarvis/core/config.py").is_file()


@pytest.mark.parametrize(("old", "new"), [("app", "app"), ("app", "appx"), ("App", "core")])
def test_names_that_could_not_be_replayed_are_refused(old, new):
    with pytest.raises(ValueError):
        codemod.Rewriter(old, new, [])


# --------------------------------------------------------------------------- compatibility


def _python(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # -S: the synthetic packages need nothing but the standard library, and a
    # developer's own editable install must not answer for them.
    return subprocess.run(
        [sys.executable, "-S", "-B", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        creationflags=_NO_WINDOW,
    )


def test_old_imports_resolve_to_the_same_module_objects(repo):
    codemod.apply(repo, OLD, NEW)
    script = (
        "import sys; sys.path.insert(0, '.')\n"
        "import jarvis.core.branding as a\n"
        "import dodaios.core.branding as b\n"
        "assert a is b, 'two copies of one module'\n"
        "a.STATE.append('x'); assert b.STATE == ['x']\n"
        "from jarvis.core.config import load\n"
        "import dodaios.core.config, dodaios, jarvis\n"
        "assert load is dodaios.core.config.load\n"
        "assert jarvis is dodaios and jarvis.__version__ == '1.2.3'\n"
        "import jarvis.brain, dodaios.brain\n"
        "assert sys.modules['jarvis.brain'] is sys.modules['dodaios.brain']\n"
        "paths = [m.__file__ for n, m in sys.modules.items() if n.endswith('core.branding')]\n"
        "assert len(set(paths)) == 1, paths\n"
        "print('ok')\n"
    )
    result = _python(repo, "-c", script)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


def test_an_import_under_the_new_name_first_is_aliased_too(repo):
    codemod.apply(repo, OLD, NEW)
    script = (
        "import sys; sys.path.insert(0, '.')\n"
        "import dodaios.core.branding as b\n"
        "import jarvis.core.branding as a\n"
        "assert a is b\n"
        "import importlib\n"
        "try:\n"
        "    importlib.import_module('jarvis.core.missing')\n"
        "except ModuleNotFoundError:\n"
        "    print('ok')\n"
    )
    result = _python(repo, "-c", script)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


@pytest.mark.parametrize(
    "module",
    [
        "jarvis",
        "jarvis.ui.web.launcher",
        "jarvis.ui.relauncher",
        "jarvis.mcp.server",
        "jarvis.mcp.agents.bridge",
    ],
)
def test_old_start_commands_still_run(repo, module):
    codemod.apply(repo, OLD, NEW)
    result = _python(repo, "-m", module)
    assert result.returncode == 0, result.stderr
    expected = "jarvis.__main__" if module == "jarvis" else module
    assert result.stdout.strip() == f"ran {expected} as __main__"


def test_a_module_reached_by_its_old_name_keeps_its_own_spec(repo):
    """The import system stamps the spec it loaded a module with on the
    module; the real one must not end up described by the old name."""
    codemod.apply(repo, OLD, NEW)
    script = (
        "import sys; sys.path.insert(0, '.')\n"
        "import jarvis.core.branding as a\n"
        "import jarvis.core as package\n"
        "assert a.__name__ == a.__spec__.name == 'dodaios.core.branding', a.__spec__\n"
        "assert package.__spec__.name == 'dodaios.core', package.__spec__\n"
        "import importlib\n"
        "assert importlib.reload(a) is sys.modules['jarvis.core.branding']\n"
        "print('ok')\n"
    )
    result = _python(repo, "-c", script)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


def test_an_install_that_only_maps_the_old_directory_still_finds_the_package(repo, tmp_path):
    """An editable install made before the move hands out the old directory
    for the old name and knows nothing of the new one."""
    codemod.apply(repo, OLD, NEW)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = (
        "import importlib.util, os, sys\n"
        f"init = {str(repo / 'jarvis' / '__init__.py')!r}\n"
        "assert importlib.util.find_spec('dodaios') is None\n"
        "spec = importlib.util.spec_from_file_location(\n"
        "    'jarvis', init, submodule_search_locations=[os.path.dirname(init)])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['jarvis'] = module\n"
        "spec.loader.exec_module(module)\n"
        "import jarvis, dodaios\n"
        "from jarvis.core.config import load\n"
        "assert jarvis is dodaios and load is dodaios.core.config.load\n"
        "print('ok')\n"
    )
    # -I: neither the working directory nor PYTHONPATH may answer for it.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        creationflags=_NO_WINDOW,
    )
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


def test_the_compatibility_package_carries_a_version_no_release_has(repo):
    codemod.apply(repo, OLD, NEW)
    stub = _read(repo, "jarvis/__init__.py")
    assert f'__version__ = "{codemod.STUB_VERSION}"' in stub
    assert '__version__ = "1.2.3"' in _read(repo, "dodaios/__init__.py")


# --------------------------------------------------------------------------- this repository


def test_no_workflow_filter_is_left_behind_on_the_old_directory():
    """Every ``paths:`` filter, ``hashFiles`` and working directory in the
    real workflows follows the package, so the move turns no lane off."""
    rewriter = codemod.Rewriter.from_tree(_REPO_ROOT, OLD, NEW)
    workflows = sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        relative = workflow.relative_to(_REPO_ROOT).as_posix()
        data, result = rewriter.rewrite(relative, workflow.read_bytes())
        assert not result.ambiguous, [hit.render() for hit in result.ambiguous]
        for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
            if codemod.KEEP_PRAGMA in line:
                continue
            for match in rewriter._token.finditer(line):
                tail = line[match.end() : match.end() + 1]
                head = line[match.start() - 1 : match.start()] if match.start() else ""
                assert not (tail == "/" and head not in ("/", ".", "-", "_")), (
                    f"{relative}:{number}: {line.strip()}"
                )
