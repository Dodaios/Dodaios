"""The shared import-name helper that the import guards rely on."""

from __future__ import annotations

import dodaios
from dodaios.core.branding import LEGACY_PACKAGE_NAMES
from tests.package_names import PACKAGE_NAME, PACKAGE_NAMES, is_package_module


def test_the_names_cover_the_imported_package_and_every_earlier_name() -> None:
    assert PACKAGE_NAME == dodaios.__name__ == dodaios.core.branding.__name__.partition(".")[0]
    assert PACKAGE_NAMES[0] == PACKAGE_NAME
    assert set(LEGACY_PACKAGE_NAMES) <= set(PACKAGE_NAMES)
    assert len(set(PACKAGE_NAMES)) == len(PACKAGE_NAMES)


def test_a_module_of_the_package_is_recognised_under_each_name() -> None:
    for name in PACKAGE_NAMES:
        assert is_package_module(name)
        assert is_package_module(f"{name}.core.config")
        assert not is_package_module(f"{name}x")
        assert not is_package_module(f"x{name}.core")


def test_other_modules_are_not_the_package() -> None:
    for name in ("", "fastapi", "tests.package_names", "os.path"):
        assert not is_package_module(name)
