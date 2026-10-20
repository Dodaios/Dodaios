"""One environment holding both distribution names is reported once, off the boot path."""

from __future__ import annotations

import logging
import threading

import pytest

from dodaios.core import distribution


@pytest.fixture(autouse=True)
def _fresh_schedule(monkeypatch):
    monkeypatch.setattr(distribution, "_scheduled", False)


def test_one_name_installed_is_quiet(caplog) -> None:
    caplog.set_level(logging.WARNING)
    for installed in ({"dodaios"}, {"personal-jarvis"}, set()):
        assert distribution.check_duplicate_distributions(
            is_installed=installed.__contains__
        ) is None
    assert caplog.records == []


def test_both_names_installed_names_the_fix(caplog) -> None:
    caplog.set_level(logging.WARNING)
    message = distribution.check_duplicate_distributions(
        is_installed={"dodaios", "personal-jarvis"}.__contains__
    )
    assert message is not None
    assert "dodaios and personal-jarvis are both installed" in message
    assert "pip uninstall -y personal-jarvis" in message
    assert "pip install --force-reinstall --no-deps dodaios" in message
    assert [record.getMessage() for record in caplog.records] == [message]


def test_the_check_reads_installed_metadata(monkeypatch) -> None:
    seen = []

    def distribution_of(name):
        seen.append(name)
        if name == "personal-jarvis":
            raise distribution.metadata.PackageNotFoundError(name)
        return object()

    monkeypatch.setattr(distribution.metadata, "distribution", distribution_of)
    assert distribution.installed_distribution_names() == ("dodaios",)
    assert seen == ["dodaios", "personal-jarvis"]


def test_the_check_runs_once_in_the_main_instance_only(monkeypatch) -> None:
    ran = threading.Event()
    monkeypatch.setattr(distribution, "check_duplicate_distributions", ran.set)
    primary = {"JARVIS_PRIMARY_INSTANCE": "1"}

    assert distribution.schedule_duplicate_distribution_check(delay_s=0, environ={}) is None
    thread = distribution.schedule_duplicate_distribution_check(delay_s=0, environ=primary)
    assert thread is not None and thread.daemon
    thread.join(timeout=5)
    assert ran.is_set()
    assert distribution.schedule_duplicate_distribution_check(delay_s=0, environ=primary) is None


def test_a_frozen_build_never_checks(monkeypatch) -> None:
    monkeypatch.setattr(distribution.sys, "frozen", True, raising=False)
    environ = {"JARVIS_PRIMARY_INSTANCE": "1"}
    assert distribution.schedule_duplicate_distribution_check(delay_s=0, environ=environ) is None


def test_a_failing_check_never_raises(monkeypatch) -> None:
    def boom():
        raise RuntimeError("metadata unreadable")

    monkeypatch.setattr(distribution, "check_duplicate_distributions", boom)
    distribution._run(0)
