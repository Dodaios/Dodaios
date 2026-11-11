# Life admin

An opt-in layer that carries the small things that slip: birthdays, appointments to book,
renewals, bills, restocks, document deadlines and follow-ups. Off until the owner turns it on in
the front page's activity panel ("Life admin").

## What it does

- **Notices** items from data the assistant already has, without a model: memory-vault facts with
  a date, contact birthdays, open loops, calendar entries and mail events (invoice, renewal,
  appointment and deadline patterns in English, German, Spanish and Portuguese). Mail that matches
  nothing is kept as a short candidate; a cheap model pass classifies candidates only on a
  subscription or local seat (`lead_triggers.wiring._seat`), never on an API key, and the
  candidates wait when no such seat is connected.
- **Prepares** the next step for items due within a week, as a stored draft: a booking or reply
  mail, a shopping list, a calendar hold, a gift idea list from saved preferences. A draft is a
  proposal. The ledger has no way to send, book or buy; acting on a draft happens through the
  normal approval card with its exact preview.
- **Delivers** in writing only: an optional weekly digest (owner-chosen day and time, a quiet lead
  routine that respects quiet hours), a section in the morning brief when the owner has one, and
  one mention in the "needs you" check for items due within 48 hours. An item is shown once per
  version (a new date or a new draft is a new version). Dismissed items never come back.

## Where it lives

`dodaios/life_admin/`: `extractors.py` (pure, deterministic), `ledger.py` (SQLite
`data/life_admin.db`), `prepare.py` (drafts), `settings.py` (stored in the society meta table),
`service.py` (scan, prepare, deliver, the digest routine). Routes: `/api/agent-chat/lead/life-admin`.
The routine context hooks are in `agent_chat/proactive_checks.py`; the mail and calendar intake
hook is `lead_triggers.wiring.submit_payload`.
