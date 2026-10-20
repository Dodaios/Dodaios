"""The primary claims the single-instance mutex under every name it has had.

An old and a new release must never run side by side: they would share the
data directory, the ports and the microphone. A primary therefore holds the
mutex under its current name and under each earlier one, and a process that
finds ANY of them taken is a secondary. The mutexes live in an in-memory
namespace (``tests/fakes/fake_win32_mutex.py``): a real ``Global\\`` name would
collide with the app running on the developer's machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.core.branding import LEGACY_WINDOWS_MUTEX_NAMES, WINDOWS_MUTEX_NAME
from dodaios.ui.shell import single_instance
from dodaios.ui.shell.single_instance import SingleInstance
from tests.fakes.fake_win32_mutex import FakeNamedMutexes

_LEGACY = LEGACY_WINDOWS_MUTEX_NAMES[0]


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(single_instance, "_is_windows", lambda: True)
    # The boot housekeeping a real primary runs is not under test here.
    monkeypatch.setattr(SingleInstance, "_on_primary_claim", lambda _self: None)


def _mutexes(monkeypatch: pytest.MonkeyPatch, *held_elsewhere: str) -> FakeNamedMutexes:
    fake = FakeNamedMutexes(held_elsewhere=held_elsewhere)
    fake.install(monkeypatch, single_instance)
    return fake


def test_the_default_instance_claims_the_current_name_and_every_earlier_one() -> None:
    assert single_instance.MUTEX_NAMES == (WINDOWS_MUTEX_NAME, *LEGACY_WINDOWS_MUTEX_NAMES)
    assert single_instance.MUTEX_NAMES[0] == single_instance.MUTEX_NAME


@pytest.mark.usefixtures("windows")
def test_a_primary_holds_both_names_until_it_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _mutexes(monkeypatch)

    claim = SingleInstance(app_dir=tmp_path).try_claim()

    assert claim is not None
    assert fake.is_held(WINDOWS_MUTEX_NAME) and fake.is_held(_LEGACY)
    claim.release()
    assert not fake.is_held(WINDOWS_MUTEX_NAME) and not fake.is_held(_LEGACY)


@pytest.mark.usefixtures("windows")
def test_a_running_primary_of_an_earlier_release_makes_this_one_secondary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The earlier release holds only its own name.
    fake = _mutexes(monkeypatch, _LEGACY)

    assert SingleInstance(app_dir=tmp_path).try_claim() is None
    # The current name this process created on the way is gone again, so it
    # cannot block the next start once the earlier release has quit.
    assert not fake.is_held(WINDOWS_MUTEX_NAME)
    assert fake.held[_LEGACY] == 1


@pytest.mark.usefixtures("windows")
def test_a_running_primary_of_this_release_makes_the_next_one_secondary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _mutexes(monkeypatch)
    first = SingleInstance(app_dir=tmp_path).try_claim()
    assert first is not None

    assert SingleInstance(app_dir=tmp_path).try_claim() is None
    # The second process stops at the first name it finds taken, and its
    # handle to it is closed again.
    assert fake.created == [WINDOWS_MUTEX_NAME, _LEGACY, WINDOWS_MUTEX_NAME]
    assert fake.held[WINDOWS_MUTEX_NAME] == 1
    first.release()

    third = SingleInstance(app_dir=tmp_path).try_claim()
    assert third is not None
    third.release()


@pytest.mark.usefixtures("windows")
def test_an_earlier_release_starting_beside_this_primary_finds_its_name_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _mutexes(monkeypatch)
    claim = SingleInstance(app_dir=tmp_path).try_claim()
    assert claim is not None

    # What an earlier release does on start: create its one name and look.
    fake.CreateMutex(None, False, _LEGACY)
    assert fake.last_error() == 183  # ERROR_ALREADY_EXISTS
    claim.release()
