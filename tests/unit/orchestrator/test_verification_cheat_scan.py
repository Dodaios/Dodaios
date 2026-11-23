"""The cheat scan: a diff that makes checks pass by weakening them is reported.

Every diff here is made by git itself from a before and an after, so the scan
is tested against the text it will really read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dodaios.orchestrator.verification import cheat_scan
from dodaios.orchestrator.verification.cheat_scan import AMBIGUOUS, VIOLATION


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout


@pytest.fixture
def diff_of(tmp_path: Path):
    """``diff_of(before, after)``: the diff git writes for that change.

    Both are ``{path: text}``; a path missing from ``after`` is deleted.
    """
    counter = iter(range(1_000))

    def make(before: dict[str, str], after: dict[str, str]) -> str:
        repo = tmp_path / f"repo{next(counter)}"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "T")
        for path, text in before.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "before")
        for path in before:
            if path not in after:
                (repo / path).unlink()
        for path, text in after.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        return _git(repo, "diff", "-M", "--cached", "HEAD")

    return make


TEST = "def test_sum():\n    assert add(1, 2) == 3\n    assert add(0, 0) == 0\n"
CODE = "def add(a, b):\n    return a + b\n"


def _found(findings) -> list[tuple[str, str, str]]:
    return [(f.rule, f.severity, f.path) for f in findings]


def test_an_honest_change_has_no_finding(diff_of):
    diff = diff_of(
        {"app/calc.py": CODE, "tests/test_calc.py": TEST},
        {
            "app/calc.py": CODE + "\n\ndef sub(a, b):\n    return a - b\n",
            "tests/test_calc.py": TEST + "\n\ndef test_sub():\n    assert sub(3, 1) == 2\n",
        },
    )
    assert cheat_scan.scan(diff) == []


def test_added_lines_carry_their_line_number_in_the_new_file(diff_of):
    diff = diff_of({"app/calc.py": CODE}, {"app/calc.py": CODE + "x = 1  # noqa\n"})
    (finding,) = cheat_scan.scan(diff)
    assert (finding.path, finding.line, finding.excerpt) == ("app/calc.py", 3, "x = 1  # noqa")


# ------------------------------------------------------------------- C1


def test_c1_a_deleted_test_file_is_a_violation(diff_of):
    diff = diff_of({"app/calc.py": CODE, "tests/test_calc.py": TEST}, {"app/calc.py": CODE})
    assert _found(cheat_scan.scan(diff)) == [("C1", VIOLATION, "tests/test_calc.py")]


def test_c1_a_renamed_test_file_or_a_deleted_source_file_is_not(diff_of):
    renamed = diff_of({"tests/test_calc.py": TEST}, {"tests/test_math.py": TEST})
    assert cheat_scan.scan(renamed) == []
    removed_code = diff_of({"app/calc.py": CODE, "app/old.py": CODE}, {"app/calc.py": CODE})
    assert cheat_scan.scan(removed_code) == []


# ------------------------------------------------------------------- C2


@pytest.mark.parametrize(
    "marker",
    ["@pytest.mark.skip(reason='later')", "@pytest.mark.xfail", "@unittest.skip('x')"],
)
def test_c2_switching_an_existing_test_off_is_a_violation(diff_of, marker):
    diff = diff_of({"tests/test_calc.py": TEST}, {"tests/test_calc.py": f"{marker}\n{TEST}"})
    assert _found(cheat_scan.scan(diff)) == [("C2", VIOLATION, "tests/test_calc.py")]


def test_c2_a_condition_on_an_existing_test_is_ambiguous(diff_of):
    marker = "@pytest.mark.skipif(sys.platform == 'win32', reason='posix only')\n"
    diff = diff_of({"tests/test_calc.py": TEST}, {"tests/test_calc.py": marker + TEST})
    assert _found(cheat_scan.scan(diff)) == [("C2", AMBIGUOUS, "tests/test_calc.py")]


def test_c2_a_skip_in_a_new_test_file_weakens_nothing(diff_of):
    diff = diff_of({}, {"tests/test_new.py": "@pytest.mark.skip\n" + TEST})
    assert cheat_scan.scan(diff) == []


def test_c2_only_narrows_the_run_even_in_a_new_test_file(diff_of):
    spec = "it.only('adds', () => {\n  expect(add(1, 2)).toBe(3);\n});\n"
    diff = diff_of({}, {"web/src/add.test.ts": spec})
    assert _found(cheat_scan.scan(diff)) == [("C2", VIOLATION, "web/src/add.test.ts")]


def test_c2_a_skip_that_only_moved_is_not_new(diff_of):
    before = "@pytest.mark.skip\ndef test_a():\n    assert True\n\n\ndef test_b():\n    assert 1\n"
    after = "def test_b():\n    assert 1\n\n\n@pytest.mark.skip\ndef test_a():\n    assert True\n"
    diff = diff_of({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert [f for f in cheat_scan.scan(diff) if f.rule == "C2"] == []


# ------------------------------------------------------------------- C3


@pytest.mark.parametrize(
    "line",
    [
        "x = compute()  # noqa",
        "x = compute()  # type: ignore",
        "x = compute()  # noqa: E501",
        "// @ts-ignore",
        "/* eslint-disable */",
        "# ruff: noqa",
    ],
)
def test_c3_a_suppression_without_a_reason_is_a_violation(diff_of, line):
    path = "web/src/a.ts" if line.startswith("/") else "app/a.py"
    diff = diff_of({path: "x = 1\n"}, {path: f"x = 1\n{line}\n"})
    assert _found(cheat_scan.scan(diff)) == [("C3", VIOLATION, path)]


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("app/a.py", "except Exception:  # noqa: BLE001 - the probe is best effort"),
        ("app/a.py", "value = load()  # type: ignore[arg-type]  # the stub lacks the overload"),
        ("web/src/a.ts", "// eslint-disable-next-line no-console -- the CLI prints on purpose"),
        ("web/src/a.ts", "// @ts-expect-error the fixture is partial on purpose"),
    ],
)
def test_c3_a_named_and_reasoned_suppression_is_ambiguous(diff_of, path, line):
    diff = diff_of({path: "x = 1\n"}, {path: f"x = 1\n{line}\n"})
    assert _found(cheat_scan.scan(diff)) == [("C3", AMBIGUOUS, path)]


def test_c3_many_reasoned_suppressions_in_one_change_are_a_violation(diff_of):
    lines = "".join(f"v{i} = f()  # noqa: BLE001 - reason {i}\n" for i in range(6))
    diff = diff_of({"app/a.py": "x = 1\n"}, {"app/a.py": "x = 1\n" + lines})
    findings = cheat_scan.scan(diff)
    assert len(findings) == 6
    assert {f.severity for f in findings} == {VIOLATION}


def test_c3_a_suppression_that_was_already_there_is_not_counted(diff_of):
    before = "a = 1\nx = f()  # noqa\n"
    diff = diff_of({"app/a.py": before}, {"app/a.py": "b = 2\n" + before})
    assert cheat_scan.scan(diff) == []


# ------------------------------------------------------------------- C4


def test_c4_a_step_made_to_pass_is_a_violation(diff_of):
    before = "jobs:\n  test:\n    steps:\n      - run: pytest\n"
    after = "jobs:\n  test:\n    steps:\n      - run: pytest\n        continue-on-error: true\n"
    diff = diff_of({".github/workflows/ci.yml": before}, {".github/workflows/ci.yml": after})
    assert _found(cheat_scan.scan(diff)) == [("C4", VIOLATION, ".github/workflows/ci.yml")]


def test_c4_any_other_change_to_a_file_that_defines_the_checks_is_ambiguous(diff_of):
    diff = diff_of(
        {"pytest.ini": "[pytest]\ntestpaths = tests\n"},
        {"pytest.ini": "[pytest]\ntestpaths = tests unit\n"},
    )
    assert _found(cheat_scan.scan(diff)) == [("C4", AMBIGUOUS, "pytest.ini")]
    conftest = diff_of(
        {"conftest.py": "import pytest\n"}, {"conftest.py": "import pytest\nX = 1\n"}
    )
    assert _found(cheat_scan.scan(conftest)) == [("C4", AMBIGUOUS, "conftest.py")]


def test_c4_a_deleted_check_file_is_a_violation(diff_of):
    diff = diff_of({"pytest.ini": "[pytest]\n", "a.py": CODE}, {"a.py": CODE})
    assert _found(cheat_scan.scan(diff)) == [("C4", VIOLATION, "pytest.ini")]


def test_c4_a_manifest_counts_only_where_it_sets_checks(diff_of):
    before = (
        '{\n  "scripts": {\n    "test": "jest"\n  },\n'
        '  "dependencies": {\n    "a": "1.0.0"\n  }\n}\n'
    )
    bumped = before.replace('"a": "1.0.0"', '"a": "1.1.0"')
    assert cheat_scan.scan(diff_of({"package.json": before}, {"package.json": bumped})) == []
    other = before.replace('"test": "jest"', '"test": "jest --ci"')
    assert _found(cheat_scan.scan(diff_of({"package.json": before}, {"package.json": other}))) == [
        ("C4", AMBIGUOUS, "package.json")
    ]
    hollow = before.replace('"test": "jest"', '"test": "jest --passWithNoTests"')
    assert _found(cheat_scan.scan(diff_of({"package.json": before}, {"package.json": hollow}))) == [
        ("C4", VIOLATION, "package.json")
    ]


def test_c4_a_lint_rule_switched_off_in_pyproject_is_reported(diff_of):
    before = '[project]\nname = "x"\n\n[tool.ruff.lint]\nselect = ["E", "F"]\n'
    after = before + 'ignore = ["E501", "F401"]\n'
    diff = diff_of({"pyproject.toml": before}, {"pyproject.toml": after})
    assert _found(cheat_scan.scan(diff)) == [("C4", AMBIGUOUS, "pyproject.toml")]
    renamed = before.replace('name = "x"', 'name = "y"')
    assert cheat_scan.scan(diff_of({"pyproject.toml": before}, {"pyproject.toml": renamed})) == []


# ------------------------------------------------------------------- C5


@pytest.mark.parametrize(
    "path",
    [".claude/settings.json", ".claude/hooks/stop.py", "scripts/agent_done_gate.py",
     ".github/agent-done-gate.json", ".husky/pre-push"],
)
def test_c5_gates_and_hooks_are_off_limits(diff_of, path):
    diff = diff_of({path: "one\n"}, {path: "one\ntwo\n"})
    assert ("C5", VIOLATION, path) in _found(cheat_scan.scan(diff))


@pytest.mark.parametrize(
    "path", ["AGENTS.md", "CLAUDE.md", "docs/sub/AGENTS.md", ".github/copilot-instructions.md"],
)
def test_c5_an_instruction_file_is_a_point_to_look_at_not_a_violation(diff_of, path):
    diff = diff_of({path: "one\n"}, {path: "one\ntwo\n"})
    found = _found(cheat_scan.scan(diff))
    assert ("C5", AMBIGUOUS, path) in found
    assert not [f for f in found if f[1] == VIOLATION]


def test_c5_an_ordinary_document_is_not_an_instruction_file(diff_of):
    diff = diff_of({"docs/agents.md.notes.txt": "a\n"}, {"docs/agents.md.notes.txt": "b\n"})
    assert cheat_scan.scan(diff) == []


# ------------------------------------------------------------------- C6


def test_c6_production_code_that_asks_for_the_test_runner_is_ambiguous(diff_of):
    after = CODE + '\nif "pytest" in sys.modules:\n    add = lambda a, b: 3\n'
    diff = diff_of({"app/calc.py": CODE}, {"app/calc.py": after})
    assert _found(cheat_scan.scan(diff)) == [("C6", AMBIGUOUS, "app/calc.py")]
    in_test = diff_of(
        {"tests/test_calc.py": TEST},
        {"tests/test_calc.py": TEST + 'NAME = os.environ["PYTEST_CURRENT_TEST"]\n'},
    )
    assert cheat_scan.scan(in_test) == []


# ------------------------------------------------------------------- C7


def test_c7_fewer_assertions_in_an_existing_test_is_ambiguous(diff_of):
    after = "def test_sum():\n    add(1, 2)\n    assert add(0, 0) == 0\n"
    diff = diff_of({"tests/test_calc.py": TEST}, {"tests/test_calc.py": after})
    (finding,) = cheat_scan.scan(diff)
    assert (finding.rule, finding.severity) == ("C7", AMBIGUOUS)
    assert "1 assertions removed, 0 added" in finding.note


def test_c7_a_test_left_without_any_assertion_is_a_violation(diff_of):
    after = "def test_sum():\n    add(1, 2)\n    add(0, 0)\n"
    diff = diff_of({"tests/test_calc.py": TEST}, {"tests/test_calc.py": after})
    (finding,) = cheat_scan.scan(diff, read_new=lambda _path: after)
    assert (finding.rule, finding.severity) == ("C7", VIOLATION)
    # Without the file's content the scan cannot know, and says only what it saw.
    (unsure,) = cheat_scan.scan(diff)
    assert unsure.severity == AMBIGUOUS


def test_c7_an_assertion_replaced_by_another_is_no_finding(diff_of):
    after = "def test_sum():\n    assert add(1, 2) == 3\n    assert add(2, 2) == 4\n"
    diff = diff_of({"tests/test_calc.py": TEST}, {"tests/test_calc.py": after})
    assert cheat_scan.scan(diff) == []


# ------------------------------------------------------------- the whole


def test_findings_come_in_file_order_and_violations_can_be_picked_out(diff_of):
    diff = diff_of(
        {"app/calc.py": CODE, "tests/test_calc.py": TEST, "tests/test_gone.py": TEST},
        {
            "app/calc.py": CODE + "y = g()  # noqa: BLE001 - optional import\n",
            "tests/test_calc.py": "@pytest.mark.skip\n" + TEST,
        },
    )
    findings = cheat_scan.scan(diff)
    assert _found(findings) == [
        ("C3", AMBIGUOUS, "app/calc.py"),
        ("C2", VIOLATION, "tests/test_calc.py"),
        ("C1", VIOLATION, "tests/test_gone.py"),
    ]
    assert [f.rule for f in cheat_scan.violations(findings)] == ["C2", "C1"]
    assert findings[0].to_dict()["rule"] == "C3"


def test_a_binary_file_and_an_empty_diff_are_skipped(diff_of):
    assert cheat_scan.scan("") == []
    assert cheat_scan.parse_diff("not a diff at all\n") == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pytest.ini", True), ("tox.ini", True), ("conftest.py", True), ("Makefile", True),
        (".eslintrc.json", True), ("eslint.config.mjs", True), ("tsconfig.json", True),
        ("tsconfig.build.json", True), ("vitest.config.ts", True),
        (".github/workflows/ci.yml", True), ("app/config.py", False), ("README.md", False),
        ("package.json", False),
    ],
)
def test_which_files_define_the_checks(path, expected):
    assert cheat_scan.defines_checks(path) is expected
