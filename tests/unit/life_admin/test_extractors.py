"""Deterministic extractors: one fixture per kind, in English and German."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from dodaios.life_admin import extractors as ex

TODAY = date(2026, 11, 11)


def _mem(text: str, due_at: str | None = None, via: str = "", id_: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(id=id_, text=text, due_at=due_at, source={"via": via} if via else {})


def test_dates_in_the_formats_people_write() -> None:
    assert ex.due_date("pay by 2026-11-20", TODAY) == date(2026, 11, 20)
    assert ex.due_date("fällig am 20.11.2026", TODAY) == date(2026, 11, 20)  # i18n-allow
    assert ex.due_date("due 20/11/26", TODAY) == date(2026, 11, 20)
    assert ex.due_date("due on November 20, 2026", TODAY) == date(2026, 11, 20)
    assert ex.due_date("bis 5. Dezember", TODAY) == date(2026, 12, 5)
    # No year: the next such day. 3 March has passed this year.
    assert ex.due_date("renews 3 March", TODAY) == date(2027, 3, 3)
    assert ex.due_date("nothing dated here", TODAY) is None


def test_a_date_after_a_due_word_wins_over_the_first_date() -> None:
    text = "Invoice dated 2026-10-01, payable until 2026-11-25."
    assert ex.due_date(text, TODAY) == date(2026, 11, 25)


def test_contact_birthday_is_the_next_occurrence() -> None:
    contacts = [
        SimpleNamespace(name="Anna Rossi", birthday="1990-11-15", slug="anna"),
        SimpleNamespace(name="Leap", birthday="2000-02-29", slug="leap"),
        SimpleNamespace(name="Nobody", birthday=None, slug="n"),
        SimpleNamespace(name="Broken", birthday="not-a-date", slug="b"),
    ]
    found = ex.from_contacts(contacts, TODAY)
    assert [(f.kind, f.subject, f.due) for f in found] == [
        ("birthday", "Anna Rossi", date(2026, 11, 15))
    ]
    far = ex.from_contacts(contacts[1:2], date(2027, 1, 20))
    assert far[0].due == date(2027, 3, 1)  # 29 February lands on 1 March in a common year


def test_vault_facts_by_kind() -> None:
    found = ex.from_memories(
        [
            _mem("Car insurance renewal for the Golf", "2026-11-20T09:00:00+00:00", id_="a"),
            _mem("Pay the electricity invoice", "2026-11-14T09:00:00+00:00", id_="b"),
            _mem("Open loop: call the dentist", "2026-11-12T17:00:00+00:00", "open_loop", "c"),
            _mem("Renew passport before the deadline", "2026-12-01T00:00:00+00:00", id_="d"),
            _mem("Buy groceries: milk and eggs", "2026-11-13T00:00:00+00:00", id_="e"),
            _mem("Old thing", "2025-01-01T00:00:00+00:00", id_="f"),
        ],
        TODAY,
    )
    kinds = {f.evidence["ref"]: f.kind for f in found}
    assert kinds == {
        "a": "renewal", "b": "bill", "c": "follow_up", "d": "renewal", "e": "shopping",
    }
    loop = next(f for f in found if f.evidence["ref"] == "c")
    assert loop.title == "call the dentist" and loop.evidence["type"] == "open_loop"


def test_birthday_named_in_a_fact_without_a_due_date() -> None:
    found = ex.from_memories([_mem("Mara's birthday is on 3 December", id_="r")], TODAY)
    assert len(found) == 1
    got = (found[0].kind, found[0].subject, found[0].due)
    assert got == ("birthday", "Mara", date(2026, 12, 3))


def test_calendar_birthdays_and_deadlines_but_not_plain_appointments() -> None:
    assert ex.from_calendar({"title": "Dentist", "start": "2026-11-14"}, TODAY) == []
    deadline = ex.from_calendar(
        {"id": "ev1", "title": "Tax return deadline", "start": "2026-11-30T00:00:00"}, TODAY
    )
    assert deadline[0].kind == "document" and deadline[0].due == date(2026, 11, 30)
    birthday = ex.from_calendar({"summary": "Tom's birthday", "date": "2026-11-18"}, TODAY)
    assert birthday[0].kind == "birthday"


def test_mail_per_kind() -> None:
    cases = [
        ({"id": "1", "subject": "Your invoice 4711", "snippet": "Pay by 2026-11-24"}, "bill"),
        ({"id": "2", "subject": "Rechnung Nr. 12", "snippet": "fällig am 20.11.2026"},  # i18n-allow
         "bill"),
        ({"id": "3", "subject": "Your subscription renews on 1 December 2026"}, "renewal"),
        ({"id": "4", "subject": "Time to book an appointment", "snippet": "by 30 November"},
         "appointment"),
        ({"id": "5", "subject": "Passport expires soon", "snippet": "expires 2026-12-15"},
         "renewal"),
        ({"id": "6", "subject": "Visa application deadline", "snippet": "submit by 2026-12-02"},
         "document"),
    ]
    for mail, kind in cases:
        found = ex.from_mail({**mail, "sender": "Shop <shop@example.com>"}, TODAY)
        assert found and found[0].kind == kind, mail
        assert found[0].evidence["type"] == "mail" and found[0].evidence["ref"] == mail["id"]


def test_marketing_and_unrelated_mail_is_left_out() -> None:
    sale = {"id": "1", "subject": "Black Friday sale: 40% off subscription"}
    old = {"id": "3", "subject": "Invoice 9", "snippet": "due 2020-01-01"}
    assert ex.from_mail(sale, TODAY) == []
    assert ex.from_mail({"id": "2", "subject": "Lunch tomorrow?"}, TODAY) == []
    assert ex.from_mail(old, TODAY) == []
    assert ex.is_candidate({"subject": "Lunch tomorrow?"})
    assert not ex.is_candidate({"subject": "Weekly newsletter"})
