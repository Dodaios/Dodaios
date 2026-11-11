"""The ledger's dedupe rules and the drafts: prepared, never sent."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from dodaios.life_admin import prepare
from dodaios.life_admin.ledger import Ledger
from dodaios.life_admin.model import DISMISSED, DONE, PREPARED, WAITING, Found, Item

TODAY = date(2026, 11, 11)


def _book(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "life.db")


def _bill(due: date = date(2026, 11, 20)) -> Found:
    return Found("bill", "Electricity invoice", due, {"type": "mail", "ref": "m1",
                                                    "sender": "Power <billing@power.example>"})


def test_same_item_is_one_row_and_a_new_date_is_a_new_version(tmp_path: Path) -> None:
    book = _book(tmp_path)
    assert book.upsert(_bill()) == "added"
    assert book.upsert(_bill()) == "kept"
    assert len(book.list_open(TODAY)) == 1
    item = book.list_open(TODAY)[0]
    assert item.version == 1
    # the same title with another due date is another item, not an update of this one
    assert book.upsert(_bill(date(2026, 12, 1))) == "added"


def test_dismissed_never_comes_back_and_done_birthdays_reopen_next_year(tmp_path: Path) -> None:
    book = _book(tmp_path)
    found = _bill()
    book.upsert(found)
    assert book.set_status(found.item_id, DISMISSED)
    assert book.upsert(found) == "kept"
    assert book.list_open(TODAY) == []

    birthday = Found("birthday", "Anna's birthday", date(2026, 11, 15), {"type": "contact"},
                     subject="Anna")
    book.upsert(birthday)
    book.set_status(birthday.item_id, DONE)
    assert book.upsert(birthday) == "kept"
    next_year = Found("birthday", "Anna's birthday", date(2027, 11, 15), {"type": "contact"},
                      subject="Anna")
    assert next_year.item_id == birthday.item_id
    assert book.upsert(next_year) == "reopened"
    assert book.get(birthday.item_id).due == date(2027, 11, 15)


def test_stale_items_drop_out_of_the_list(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.upsert(_bill(date(2026, 9, 1)))
    assert book.list_open(TODAY) == []


def test_draft_bumps_the_version_and_showing_it_makes_it_wait_for_a_yes(tmp_path: Path) -> None:
    book = _book(tmp_path)
    found = _bill()
    book.upsert(found)
    item = book.get(found.item_id)
    book.set_draft(found.item_id, prepare.build_draft(item))
    prepared = book.get(found.item_id)
    assert (prepared.status, prepared.version) == (PREPARED, 2)
    book.mark_shown([prepared])
    shown = book.get(found.item_id)
    assert shown.status == WAITING and shown.shown_version == shown.version


def _item(kind: str, **evidence: str):
    found = Found(kind, "Thing", date(2026, 11, 14), {"type": "mail", **evidence}, subject="Mara")
    return Item(found.item_id, kind, "Thing", found.due, "noticed", found.evidence, "Mara")


def test_every_kind_gets_a_draft_that_is_unsent_and_needs_approval() -> None:
    for kind in ("birthday", "appointment", "renewal", "bill", "shopping", "document", "follow_up"):
        draft = prepare.build_draft(_item(kind, sender="Clinic <info@clinic.example>"))
        assert draft["sent"] is False and draft["requires_approval"] is True, kind
        assert "Nothing has been sent" in draft["how"]
        assert draft["kind"] in (prepare.MAIL, prepare.LIST, prepare.HOLD, prepare.IDEAS)


def test_booking_mail_goes_to_the_sender_and_gift_ideas_use_saved_likes() -> None:
    mail = prepare.build_draft(_item("appointment", sender="Clinic <info@clinic.example>"))
    assert mail["kind"] == prepare.MAIL and mail["to"] == "info@clinic.example"
    ideas = prepare.build_draft(_item("birthday"), preferences=lambda who: [f"{who} likes tea"])
    assert ideas["kind"] == prepare.IDEAS and ideas["lines"] == ["Mara likes tea"]
    empty = prepare.build_draft(_item("birthday"), preferences=lambda who: [])
    assert "No saved likes" in empty["lines"][0]


def test_german_drafts_use_real_umlauts() -> None:
    draft = prepare.build_draft(_item("appointment"), lang="de")
    assert "möchte" in draft["body"] and "Grüße" in draft["body"]  # i18n-allow


def test_the_module_has_no_way_to_send_or_buy() -> None:
    names = {n.lower() for n in dir(prepare)} | {n.lower() for n in dir(Ledger)}
    assert not [n for n in names if n.startswith(("send", "buy", "book_", "pay"))]
