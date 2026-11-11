# Event triggers for the lead

Mail, calendar changes, code-host notifications and CI results, automation
events and chat messages that are not requests are input for the assistant.
They reach it through one intake (`dodaios/lead_triggers/`) that is quiet by
default.

## Flow

1. **One event shape.** Every producer builds a `TriggerEvent`: source, scope,
   sender, thread key, summary, ids, received time, raw reference. The body is
   never copied; the reference says where to read it again. All of it is data.
2. **Stage 1, code only.** Per source the owner picks `explicit only`
   (default), `candidate` or `ignore`. Candidates pass allow-lists (senders,
   repos or calendars), bot and self filtering, a per-source rate limit and
   dedupe by event id and by thread key. Every drop is counted by reason and
   shown in the app.
3. **Stage 2, a model on candidates only.** The owner's prose rules (for
   example "tell me when a customer writes about an invoice") are applied to
   all candidates that arrive together in one call. The answer per event is
   `ignore`, `note` (a line in the next brief), `act` (a one-shot lead
   routine, so jobs, the billing hold and approvals apply) or `ask` (one
   written notice). Any action must cite a rule that exists and covers the
   event's source, otherwise code turns it into `ignore`.
4. **Accept mode.** `off`, `observe` (default) or `auto`. While observing,
   nothing acts and nothing is written to the owner; the decision list records
   "would have done X because rule Y". A single rule can be promoted to act
   while the install keeps observing.

## Safety

- External text is quoted data inside a fenced block of the prompt and inside
  the work order of an `act` job. A trigger cannot widen what the assistant may
  do; sends, changes and deletes still go through the risk tiers and approvals.
- The model runs on a connected subscription only. With none connected,
  candidates wait (up to a day); no API key is ever used.
- Notices are written, never spoken, deduplicated per rule and thread for a
  day, and held during the owner's quiet hours.

## Producers

- `POST /api/agent-chat/lead/triggers/events` with `{source, payload}` for
  mail, calendar and code-host connectors.
- Integration events published on the app bus (`mail.*`, `calendar.*`,
  `github.*`, anything else becomes `automation`) and finished missions.
- Chat messages that do not belong to the owner's private chat.

Settings and the decision log live in the society store; the app shows them in
the activity panel next to the proactivity settings.

## Thread subscriptions and direct delivery

A job that starts from an event on a thread (a mail conversation, a PR, a chat
topic, a calendar invite) subscribes to that thread key: an `act` decision does
it itself, and the lead does it with `follow_thread` right after a hand-off.
The table is many-to-many (`thread_subscriptions.db`).

- Later events on the thread pass stage 1 and are then handed to the owning job
  by code, with no model decision, through the kind's own message path (an
  agent's chat for a society assignment, the pane prompt for a coding pane).
  The lead's model only sees events nobody owns, or that the job could not take
  (`busy`, `gone`, no direct path for the kind): those fall back to the lead as
  ordinary candidates.
- A worker can return an event outside its task with `handback_event(event_id,
  reason)`, optionally unsubscribing. The lead gets it as a normal candidate; it
  never bounces back to the same owner.
- Authority is separate from information. The mandate the job started under
  (origin, policy, source, scope) is stored once and re-checked before every
  delivery; a delivered event is quoted data and grants nothing. A removed
  policy or another scope sends the event to the lead instead.
- An owner stop hold blocks direct delivery (`hold` hook of the service).
- Subscriptions end with their job (the jobs ledger's end listener).
- Measured in the trigger view (`delivery.direct`, `delivery.lead_decisions`,
  `delivery.handed_back`), the decision log (`deliver` entries) and
  `watchdog_status` (`event_routing`).
