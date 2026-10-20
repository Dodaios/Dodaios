"""Package list of the distribution; everything else is in pyproject.toml.

pyproject.toml cannot say this one thing: the top-level ``jarvis`` package
(the alias that keeps ``python -m jarvis`` and ``import jarvis.x`` working for
autostart entries and MCP registrations written before the rename) is built
from ``dodaios/_legacy_alias``, so the repository needs no ``jarvis`` folder.
``[tool.setuptools.packages.find]`` only finds a package under its own folder
name, and a ``packages`` table there would override this file, so the list
lives here.
"""

from __future__ import annotations

from setuptools import find_packages, setup

#: The earlier package name and the folder it is built from.
LEGACY_PACKAGE = "jarvis"
LEGACY_PACKAGE_DIR = "dodaios/_legacy_alias"

#: ``conductor`` is the scheduled-jobs engine behind /api/conductor/* and the
#: ``dodaios conductor`` commands. Left out, it imported only when the app ran
#: with the checkout as its working directory (run.bat), so the console script,
#: autostart and every wheel install served no Conductor API at all.
INCLUDE = ("dodaios*", "conductor*")
EXCLUDE = ("*.__pycache__", "*.__pycache__.*", "dodaios._legacy_alias")


def packages(where: str = ".") -> list[str]:
    """Every package the distribution ships, the legacy alias included."""
    return [*find_packages(where=where, include=INCLUDE, exclude=EXCLUDE), LEGACY_PACKAGE]


if __name__ == "__main__":
    setup(packages=packages(), package_dir={LEGACY_PACKAGE: LEGACY_PACKAGE_DIR})
