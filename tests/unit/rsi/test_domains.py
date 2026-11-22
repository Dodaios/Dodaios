"""Domains from paths: ordered rules, shares, and the tag a brief gets before it runs."""

from __future__ import annotations

import pytest

from dodaios.rsi import domains


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/unit/rsi/test_domains.py", "testing"),
        ("src/app/Button.test.tsx", "testing"),
        ("pkg/server_test.go", "testing"),
        ("conftest.py", "testing"),
        ("db/migrations/0003_add_column.py", "database"),
        ("dodaios/memory/schema.sql", "database"),
        (".github/workflows/ci.yml", "infra_ci"),
        ("Dockerfile", "infra_ci"),
        ("scripts/ci/run_gates.py", "infra_ci"),
        ("docs/routines.md", "docs"),
        ("README.md", "docs"),
        ("dodaios/ui/web/frontend/src/components/Chat.tsx", "frontend"),
        ("styles/main.css", "frontend"),
        ("dodaios/ui/web/server.py", "backend"),
        ("cmd/main.go", "backend"),
        ("assets/logo.png", "other"),
        ("dodaios.toml", "other"),
    ],
)
def test_one_path_has_one_domain(path, expected):
    assert domains.domain_of(path) == expected


def test_a_folder_name_alone_never_makes_a_file_frontend():
    assert domains.domain_of("dodaios/ui/web/agent_chat_routes.py") == "backend"


def test_a_script_is_frontend_only_inside_a_known_frontend_root():
    path = "dodaios/ui/web/frontend/src/lib/api.ts"
    assert domains.domain_of(path) == "backend"
    assert domains.domain_of(path, frontend_roots=["dodaios/ui/web/frontend"]) == "frontend"
    assert domains.domain_of("server/src/api.ts", frontend_roots=["web"]) == "backend"


def test_windows_separators_read_like_posix_ones():
    assert domains.domain_of("tests\\unit\\test_x.py") == "testing"


def test_domains_are_ranked_by_their_share_of_the_paths():
    paths = ["a/x.py", "a/y.py", "a/z.py", "web/App.tsx", "web/Nav.tsx"]
    assert domains.classify_paths(paths) == ["backend", "frontend"]
    assert domains.primary(paths) == "backend"


def test_a_small_share_does_not_count_unless_one_path_is_enough():
    many_backend = [f"pkg/m{i}.py" for i in range(9)]
    assert domains.classify_paths([*many_backend, "README.md"]) == ["backend"]
    # One migration among many files is still database work.
    assert domains.classify_paths([*many_backend, "db/migrations/0001.sql"]) == [
        "backend",
        "database",
    ]


def test_no_paths_is_no_domain_and_the_fallback_primary():
    assert domains.classify_paths([]) == []
    assert domains.primary(["", "  "]) == domains.FALLBACK


def test_every_result_is_in_the_vocabulary():
    for path in ("a.py", "a.tsx", "a.sql", "a.md", ".github/x.yml", "tests/a.py", "a.bin"):
        assert domains.domain_of(path) in domains.DOMAINS


def test_paths_named_in_a_brief_are_found_once_and_in_order():
    brief = (
        "## Task\nFix the crash in @dodaios/agent_chat/service.py when a turn ends.\n"
        "## Key files\n- @dodaios/agent_chat/service.py\n- tests/unit/agent_chat/test_service.py"
    )
    assert domains.paths_in_text(brief) == [
        "dodaios/agent_chat/service.py",
        "tests/unit/agent_chat/test_service.py",
    ]


def test_a_brief_is_tagged_from_its_paths_before_it_runs():
    found, main, source = domains.pre_classify(
        "Make the button in src/components/Send.tsx and src/components/Bar.tsx larger."
    )
    assert (found, main, source) == (["frontend"], "frontend", "paths")


def test_a_refactoring_keeps_the_domain_of_its_files_as_primary():
    found, main, source = domains.pre_classify(
        "Refactor dodaios/orchestrator/jobs.py: extract the probe handling into a module."
    )
    assert found == ["backend", "refactoring"]
    assert main == "backend"
    assert source == "paths"


def test_a_brief_without_paths_falls_back_and_says_so():
    assert domains.pre_classify("Find out why the app is slow.") == ([], "other", "fallback")
    assert domains.pre_classify("Rename the helper everywhere.") == (
        ["refactoring"],
        "other",
        "wording",
    )
