"""Copy stored credentials from the legacy keyring service to the current one, once.

The credential-store service was renamed (``dodaios.core.branding``:
``LEGACY_KEYRING_SERVICE_NAMES`` -> ``KEYRING_SERVICE_NAME``). Nothing depends
on this copy for correctness: ``dodaios.core.config.get_secret`` reads the
legacy service whenever the current one has no value for a slot, and
``delete_secret`` clears both. The copy only lets most reads stop at the
current service, and it is what eventually leaves the legacy entries as
nothing more than the way back for a downgrade.

How it runs (AP-26): :func:`schedule_credential_migration` starts one daemon
thread, in the main instance only, a while after the server is up. The
thread copies through :func:`dodaios.core.identity_migration.migrate_keyring`
(never overwrites a current value, never deletes a legacy one, reads every
copy back, writes a ``__migrated_from__<legacy>`` marker so a later start
skips the work) over each store ``get_secret`` reads:

* the platform store (Windows Credential Manager, Secret Service, macOS
  Keychain). On macOS every key lives in one vault entry, so the vault is
  copied in one write (``DarwinBundleKeyringBackend.copy_vault``) instead of
  rewriting it once per key, and the user sees no prompt per key;
* the 0600 file fallback, which can list its own entries.

A process that never runs it (a second instance, a CLI, a test) loses
nothing, and a run cut short is simply finished by the next start.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dodaios.core.identity_migration import (
    KeyringMigration,
    KeyringOutcome,
    keyring_marker_key,
    migrate_keyring,
)

log = logging.getLogger(__name__)

# Long enough that the voice and UI boot is over before the first credential
# read of the copy: it competes with nothing the user is waiting for.
DEFAULT_DELAY_S = 20.0
PRIMARY_INSTANCE_ENV_VAR = "JARVIS_PRIMARY_INSTANCE"

_SCHEDULE_LOCK = threading.Lock()
_scheduled = False


@dataclass(frozen=True, slots=True)
class StoreMigration:
    """One store's part of a run. Key names only, never a value."""

    store: str
    legacy_service: str
    current_service: str
    outcome: str
    copied: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    @classmethod
    def from_engine(cls, store: str, result: KeyringMigration) -> StoreMigration:
        return cls(
            store=store,
            legacy_service=result.legacy_service,
            current_service=result.current_service,
            outcome=result.outcome.value,
            copied=result.copied,
            kept=result.kept,
            failed=result.failed,
        )


class _LegacyReadOnly:
    """A backend whose reads of the legacy service never write anything.

    The macOS vault wrapper folds a per-item entry into the vault on a normal
    read; through this view a legacy read is a ``peek`` and a write to the
    legacy service is refused outright, so the copy cannot change the way back.
    """

    def __init__(self, backend: Any, legacy_service: str) -> None:
        self._backend = backend
        self._legacy = legacy_service

    def get_password(self, service: str, key: str) -> str | None:
        if service == self._legacy:
            peek = getattr(self._backend, "peek_password", None)
            if callable(peek):
                return peek(service, key)
        return self._backend.get_password(service, key)

    def set_password(self, service: str, key: str, value: str) -> None:
        if service == self._legacy:
            raise PermissionError("the legacy credential service is never written by the copy")
        self._backend.set_password(service, key, value)

    def delete_password(self, service: str, key: str) -> None:
        raise PermissionError("the credential copy never deletes")


class _FileStoreKeyring:
    """The 0600 file fallback in the ``keyring`` call shape."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_password(self, service: str, key: str) -> str | None:
        return self._store.get(service, key)

    def set_password(self, service: str, key: str, value: str) -> None:
        self._store.set(service, key, value)

    def delete_password(self, service: str, key: str) -> None:
        self._store.delete(service, key)

    def usernames(self, service: str) -> tuple[str, ...]:
        return self._store.usernames(service)


def _usable_platform_backend(cfg: Any) -> Any | None:
    """The live OS credential store, or ``None`` when the process runs on the file store.

    A process that fell back to the file store after a platform failure is not
    a good moment to copy into the platform store: every write would fail.
    The legacy entries stay readable through ``get_secret`` meanwhile.
    """
    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception as exc:  # noqa: BLE001 — no keyring module: nothing to copy there
        log.info("Credential copy: no OS credential store (%s).", type(exc).__name__)
        return None
    if getattr(backend, "_jarvis_file_backend", False):
        return None
    return backend if cfg._is_platform_keyring_backend(backend) else None


def _migrate_platform(
    backend: Any, legacy: str, current: str, keys: set[str]
) -> list[StoreMigration]:
    results: list[StoreMigration] = []
    marker = keyring_marker_key(legacy)
    copy_vault = getattr(backend, "copy_vault", None)
    if callable(copy_vault):
        vault = copy_vault(legacy, current, marker=marker)
        outcome = getattr(vault.outcome, "value", str(vault.outcome))
        results.append(
            StoreMigration("keychain-vault", legacy, current, outcome, copied=vault.copied)
        )
        if outcome in {"copied", "already_copied"}:
            return results
        # No usable legacy vault: entries may still exist one item each, from
        # before the vault existed. Its keys, if it could be read, join the list.
        stored_keys = getattr(backend, "stored_keys", None)
        if callable(stored_keys):
            keys = keys | set(stored_keys(legacy))
    result = migrate_keyring(
        _LegacyReadOnly(backend, legacy),
        legacy_service=legacy,
        current_service=current,
        keys=sorted(keys),
    )
    results.append(StoreMigration.from_engine("platform", result))
    return results


def _migrate_file_store(cfg: Any, legacy: str, current: str) -> StoreMigration | None:
    store = _FileStoreKeyring(cfg._FileCredStore())
    try:
        legacy_keys = store.usernames(legacy)
    except Exception as exc:  # noqa: BLE001 — an unreadable file store holds nothing to copy
        log.warning("Credential copy: file store not readable (%s).", type(exc).__name__)
        return None
    if not legacy_keys:
        # Nothing filed there under the old name: no marker either, so a
        # machine that never used the file store does not get one created.
        return None
    result = migrate_keyring(
        _LegacyReadOnly(store, legacy),
        legacy_service=legacy,
        current_service=current,
        keys=sorted(legacy_keys),
    )
    return StoreMigration.from_engine("file", result)


def migrate_credentials(*, keys: Iterable[str] | None = None) -> tuple[StoreMigration, ...]:
    """Copy every legacy credential this install can name to the current service.

    ``keys`` replaces the names from ``dodaios.core.secret_slots`` (tests).
    Safe to call again: a store that carries the marker is skipped after one
    read. Logs one summary line per store.
    """
    from dodaios.core import config as cfg

    cfg._ensure_keyring_backend()
    current = cfg.KEYRING_SERVICE
    if keys is None:
        from dodaios.core.secret_slots import all_secret_keys

        names = set(all_secret_keys())
    else:
        names = set(keys)

    results: list[StoreMigration] = []
    for legacy in cfg.LEGACY_KEYRING_SERVICES:
        platform = _usable_platform_backend(cfg)
        if platform is not None:
            results.extend(_migrate_platform(platform, legacy, current, names))
        file_result = _migrate_file_store(cfg, legacy, current)
        if file_result is not None:
            results.append(file_result)

    for result in results:
        log.info(
            "Credential copy %s -> %s (%s): %s, %d copied, %d already present, %d failed%s",
            result.legacy_service,
            result.current_service,
            result.store,
            result.outcome,
            len(result.copied),
            len(result.kept),
            len(result.failed),
            f" ({', '.join(result.failed)})" if result.failed else "",
        )
    if any(r.outcome == KeyringOutcome.INCOMPLETE.value for r in results):
        log.info("Credential copy is retried on the next start; nothing is lost meanwhile.")
    return tuple(results)


def _run(delay_s: float) -> None:
    if delay_s > 0:
        time.sleep(delay_s)
    try:
        migrate_credentials()
    except Exception:  # noqa: BLE001 — a background copy must never take the app down
        log.warning("Credential copy failed; legacy keys stay readable.", exc_info=True)


def schedule_credential_migration(
    *,
    delay_s: float = DEFAULT_DELAY_S,
    environ: Mapping[str, str] | None = None,
) -> threading.Thread | None:
    """Start the one-time copy in a daemon thread, main instance only, once per process.

    Returns the thread, or ``None`` when this process does not run it: not the
    main instance (``JARVIS_PRIMARY_INSTANCE`` is set to ``1`` only by the
    launcher that holds the single-instance lock), already started, or no
    legacy service to copy from.
    """
    global _scheduled
    from dodaios.core import config as cfg

    env = os.environ if environ is None else environ
    if env.get(PRIMARY_INSTANCE_ENV_VAR) != "1":
        log.debug("Credential copy not scheduled: not the main instance.")
        return None
    if not cfg.LEGACY_KEYRING_SERVICES:
        return None
    with _SCHEDULE_LOCK:
        if _scheduled:
            return None
        _scheduled = True
    thread = threading.Thread(
        target=_run,
        args=(delay_s,),
        name="credential-migration",
        daemon=True,
    )
    thread.start()
    return thread


__all__ = [
    "DEFAULT_DELAY_S",
    "StoreMigration",
    "migrate_credentials",
    "schedule_credential_migration",
]
