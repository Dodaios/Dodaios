from pathlib import Path

import pytest

from dodaios.core import paths


def test_product_docs_are_the_reader_registry_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "docs" / "product").mkdir(parents=True)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)

    assert paths.default_doc_roots() == [tmp_path / "docs" / "product"]


def test_engineering_docs_are_never_exposed_as_reader_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        paths.sysconfig,
        "get_path",
        lambda _name, **_kwargs: str(tmp_path / "empty"),
    )

    assert paths.default_doc_roots() == []


@pytest.mark.parametrize("distribution", ["dodaios", "personal-jarvis"])
def test_installed_wheel_docs_are_used_without_a_source_tree(
    monkeypatch,
    tmp_path: Path,
    distribution: str,
) -> None:
    # A wheel under the earlier distribution name installs its earlier share dir.
    data_root = tmp_path / "environment"
    installed = data_root / "share" / distribution / "docs"
    installed.mkdir(parents=True)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(paths.sysconfig, "get_path", lambda _name, **_kwargs: str(data_root))

    assert paths.default_doc_roots() == [installed]


def test_the_current_distribution_docs_win_over_the_earlier_ones(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "environment"
    current = data_root / "share" / "dodaios" / "docs"
    for docs in (current, data_root / "share" / "personal-jarvis" / "docs"):
        docs.mkdir(parents=True)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(paths.sysconfig, "get_path", lambda _name, **_kwargs: str(data_root))

    assert paths.default_doc_roots() == [current]


def test_user_install_scheme_docs_are_discovered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    environment = tmp_path / "environment"
    user_data = tmp_path / "user-data"
    installed = user_data / "share" / "personal-jarvis" / "docs"
    installed.mkdir(parents=True)
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(paths.sysconfig, "get_preferred_scheme", lambda _key: "user")
    monkeypatch.setattr(
        paths.sysconfig,
        "get_path",
        lambda _name, **kwargs: str(user_data if kwargs.get("scheme") else environment),
    )

    assert paths.default_doc_roots() == [installed]


def test_target_install_docs_are_discovered_next_to_package(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    installed = target / "share" / "personal-jarvis" / "docs"
    installed.mkdir(parents=True)
    monkeypatch.setattr(paths, "repo_root", lambda: target)
    monkeypatch.setattr(
        paths.sysconfig,
        "get_path",
        lambda _name, **_kwargs: str(tmp_path / "empty"),
    )

    assert paths.default_doc_roots() == [installed]
