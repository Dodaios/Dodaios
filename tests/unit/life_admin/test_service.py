"""Life admin at run time: off by default, once per version, never a key, never sent."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from dodaios.life_admin import service as life
from dodaios.life_admin.settings import LifeAdminSettings, save_settings

TODAY = date(2026, 11, 11)


class FakeStore:
    def __init__(self) -> None:
        self.meta: dict[str, str] = {}

    async def get_meta(self, key: str, default: str = "") -> str:
        return self.meta.get(key, default)

    async def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    store = FakeStore()
    monkeypatch.setattr(life, "_store", lambda: store)
    monkeypatch.setattr(life, "ledger_path", lambda: tmp_path / "life.db")
    monkeypatch.setattr(life, "_today", lambda tz: TODAY)
    monkeypatch.setattr(life, "_quiet", lambda: False)
    monkeypatch.setattr(life, "scan_local", lambda *a, **k: 0)  # no vault, no contacts here
    monkeypatch.setattr(life, "_preferences", lambda name: [])
    monkeypatch.setattr(life, "_language", lambda text: "en")
    life._ledgers.clear()
    return store


async def _enable(store: FakeStore, **changes: Any) -> LifeAdminSettings:
    cfg = LifeAdminSettings(enabled=True, digest_day="mon", **changes)
    await save_settings(cfg, store)
    return cfg


BILL = {
    "id": "m1", "subject": "Invoice 77", "snippet": "please pay by 2026-11-12",
    "sender": "Power <billing@power.example>",
}
RENEWAL = {"id": "m2", "subject": "Your subscription renews", "snippet": "on 2026-11-30"}


async def test_off_by_default_does_nothing(env: FakeStore, tmp_path: Path) -> None:
    assert LifeAdminSettings().enabled is False and LifeAdminSettings().digest_day == "off"
    assert await life.ingest_event("mail", BILL) == 0
    assert await life.urgent_context() == ""
    assert await life.brief_context() == ""
    assert await life.digest_context() == ""
    assert await life.peek_urgent_count() == 0
    assert await life.digest_skip_reason() == "life admin digest is off"
    assert not (tmp_path / "life.db").exists()  # not even a ledger file


async def test_mail_becomes_an_item_and_urgent_items_show_once(env: FakeStore) -> None:
    await _enable(env)
    assert await life.ingest_event("mail", BILL) == 1
    assert await life.ingest_event("mail", BILL) == 0  # the same mail again adds nothing
    assert await life.peek_urgent_count() == 1  # a peek hands nothing out
    first = await life.urgent_context()
    assert "Invoice 77" in first and "prepared, not sent" in first
    assert await life.urgent_context() == ""
    assert await life.peek_urgent_count() == 0


async def test_digest_is_deduplicated_across_brief_and_urgent(env: FakeStore) -> None:
    await _enable(env)
    await life.ingest_event("mail", BILL)  # urgent: due tomorrow
    await life.ingest_event("mail", RENEWAL)  # due in 19 days: not in the digest window
    assert "Invoice 77" in await life.urgent_context()
    assert await life.digest_context() == ""  # already shown, not repeated
    assert await life.digest_skip_reason() == "nothing new for the digest"
    # a new item shows once in the digest, then never again
    new = {"id": "m3", "subject": "Invoice 78", "snippet": "by 2026-11-22"}
    await life.ingest_event("mail", new)
    assert "Invoice 78" in await life.digest_context()
    assert await life.digest_context() == ""


async def test_a_new_draft_is_shown_once_more(env: FakeStore) -> None:
    await _enable(env)
    mail = {"id": "m4", "subject": "Invoice 90", "snippet": "by 2026-11-20"}
    await life.ingest_event("mail", mail)
    book = life.ledger()
    item = book.list_open(TODAY)[0]
    book.mark_shown([item])
    assert await life.digest_context() == ""
    prepared = await life.prepare_item(item.id)
    assert prepared and prepared["draft"]["sent"] is False
    again = await life.digest_context()
    assert "Invoice 90" in again and "prepared, not sent" in again


async def test_due_soon_items_are_prepared_but_not_sent(env: FakeStore) -> None:
    cfg = await _enable(env)
    await life.ingest_event("mail", BILL)
    book = life.ledger()
    assert life.prepare_due(book, cfg, TODAY) == 1
    item = book.list_open(TODAY)[0]
    assert item.draft and item.draft["sent"] is False and item.draft["requires_approval"] is True
    assert life.prepare_due(book, cfg, TODAY) == 0  # a second pass makes no second draft


async def test_dismissed_items_never_return(env: FakeStore) -> None:
    await _enable(env)
    await life.ingest_event("mail", BILL)
    item_id = life.ledger().list_open(TODAY)[0].id
    assert await life.dismiss_item(item_id)
    assert await life.ingest_event("mail", BILL) == 0
    assert await life.urgent_context() == ""
    assert life.ledger().list_open(TODAY) == []


async def test_categories_off_are_not_collected(env: FakeStore) -> None:
    await _enable(env, categories={"bill": False})
    assert await life.ingest_event("mail", BILL) == 0
    assert await life.ingest_event("mail", RENEWAL) == 1


async def test_brief_section_follows_the_in_brief_switch(env: FakeStore) -> None:
    await _enable(env, in_brief=False)
    await life.ingest_event("mail", BILL)
    assert await life.brief_context() == ""
    await _enable(env, in_brief=True)
    assert "Invoice 77" in await life.brief_context()


async def test_digest_waits_in_quiet_hours(env: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable(env)
    await life.ingest_event("mail", BILL)
    monkeypatch.setattr(life, "_quiet", lambda: True)
    assert await life.digest_skip_reason() == "quiet hours"
    monkeypatch.setattr(life, "_quiet", lambda: False)
    assert await life.digest_skip_reason() == ""


async def test_unmatched_mail_is_classified_only_on_a_subscription_seat(
    env: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _enable(env)
    mail = {
        "id": "c1", "subject": "About the garage", "snippet": "Your car is ready, 2026-11-20",
        "sender": "Garage <g@example.com>",
    }
    assert await life.ingest_event("mail", mail) == 0
    assert [c["ref"] for c in life.ledger().candidates()] == ["c1"]

    seats: list[str] = []

    async def no_seat(prompt: str) -> None:
        seats.append(prompt)

    monkeypatch.setattr("dodaios.lead_triggers.wiring._seat", no_seat)
    assert await life.classify_pending() == 0  # no subscription: the candidate waits
    assert len(seats) == 1 and "untrusted" in seats[0]
    assert life.ledger().candidates()

    async def answer(prompt: str) -> str:
        return (
            'noise [{"ref": "c1", "kind": "bill", "title": "Garage bill", "due": "2026-11-20"},'
            ' {"ref": "zzz", "kind": "bill", "title": "x"}] tail'
        )

    assert await life.classify_pending(answer) == 1
    assert life.ledger().candidates() == []
    assert life.ledger().list_open(TODAY)[0].title == "Garage bill"


def test_malformed_model_answers_produce_nothing() -> None:
    cands = [{"ref": "a", "sender": "", "subject": "s", "snippet": "", "received": ""}]
    for answer in (
        "", "no json", "[1, 2]", '[{"ref": "a", "kind": "bogus", "title": "t"}]',
        '[{"ref": "a", "kind": "birthday", "title": "t"}]', '{"ref": "a"}', "[{",
    ):
        assert life.parse_classification(answer, cands) == []


def test_the_model_pass_never_reaches_a_key_seat() -> None:
    import inspect

    source = inspect.getsource(life)
    # the only model entry point is the subscription-only seat of the trigger intake
    assert "from dodaios.lead_triggers.wiring import _seat" in source
    for banned in ("resolve_brain(", "api_key", "get_secret", "ANTHROPIC", "OPENAI"):
        assert banned not in source


def test_the_service_has_no_send_path() -> None:
    names = {n.lower() for n in dir(life)}
    assert not [n for n in names if n.startswith(("send", "buy", "post_notice", "speak"))]
