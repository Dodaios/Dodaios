"""End-to-end wiring: ContactStore write → notify sink → bus → mirror → page."""
from __future__ import annotations

import asyncio

import pytest

from dodaios.contacts import notify
from dodaios.contacts.store import ContactStore
from dodaios.core.bus import EventBus
from dodaios.memory.wiki.atomic_writer import AtomicWriter
from dodaios.memory.wiki.contact_mirror import wire_contact_mirror
from dodaios.memory.wiki.page import MarkdownPageRepository


@pytest.fixture(autouse=True)
def _clean_sink():
    notify.clear_contact_change_sink()
    yield
    notify.clear_contact_change_sink()


async def _wait_for(predicate, timeout_s: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def test_contact_write_lands_as_person_page(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    store = ContactStore(base_dir=tmp_path / "contacts")
    writer = AtomicWriter(
        vault_root=vault,
        backup_dir=tmp_path / "backups",
        concurrent_edit_lock_seconds=0.0,
    )
    bus = EventBus()
    mirror, cleanup = wire_contact_mirror(
        bus=bus,
        vault_root=vault,
        writer=writer,
        repo=MarkdownPageRepository(),
        store=store,
    )
    try:
        contact = store.put(name="Christoph Meyer", relationship="friend")
        page = vault / "people" / f"{contact.slug}.md"
        assert await _wait_for(page.exists)
        store.delete(contact.slug)
        assert await _wait_for(lambda: not page.exists())
    finally:
        cleanup()


async def test_cleanup_detaches_everything(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    store = ContactStore(base_dir=tmp_path / "contacts")
    writer = AtomicWriter(
        vault_root=vault,
        backup_dir=tmp_path / "backups",
        concurrent_edit_lock_seconds=0.0,
    )
    bus = EventBus()
    mirror, cleanup = wire_contact_mirror(
        bus=bus,
        vault_root=vault,
        writer=writer,
        repo=MarkdownPageRepository(),
        store=store,
    )
    cleanup()
    contact = store.put(name="Laura")
    await asyncio.sleep(0.1)
    assert not (vault / "people" / f"{contact.slug}.md").exists()
