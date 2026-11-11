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
