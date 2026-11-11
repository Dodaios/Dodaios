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

Code-only pollers (`dodaios/lead_triggers/producers/`) read the owner's own
connected accounts through the plugin token store, with the same refresh the
tools use. They never call a model and never use an API key.

| Poller | Reads | Incremental by |
| --- | --- | --- |
| Gmail | new inbox mail: id, thread, sender, subject, snippet, labels | history id (a 404 starts again from now) |
| Google Calendar | new invites, changes, cancellations, "starting in 15 minutes" | `updatedMin` plus a remembered set of starts |
| GitHub | notifications: review requests, mentions, CI results | ETag, `X-Poll-Interval`, remembered update times |
| Own inbox | mail that reached the assistant's own address (see below) | timestamp plus remembered ids |

- The first poll of a source only marks the present; old mail is never replayed.
- Interval 180 s by default (60 s to 1 h, `poll_interval_s`). Errors back off
  exponentially up to 30 min, a rate limit waits what the provider says, a dead
  token is retried every 15 min and shown as "reconnect".
- A poller asks its provider nothing while its toggle is off, the accept mode
  is `off`, its source is not set to `candidate`, or a stop hold covers triggers
  (`wiring.set_hold_check`). It keeps its cursor and resumes.
- Only the instance that owns ambient duties polls. Cursors and per-poller
  state (connected, state, last event, last error) live in the society store and
  are shown with a toggle in the triggers settings.
- Other producers: `POST /api/agent-chat/lead/triggers/events`, integration
  events on the app bus, finished missions and chat messages that are not
  requests.

## The assistant's own mail address

The owner can give the assistant an address (`agent_address`, for example an
inbox of the connected AgentMail plugin) and the senders who may send it work
(`agent_senders`, default the owner's own addresses).

- Mail the owner delegates is sent from that address through the connected
  inbox tools, not from the owner's personal account. The brief and the
  AgentMail usage card say so.
- Mail that reaches the address (read by the own-inbox poller, or by the Gmail
  poller when the address is an alias) takes a separate route. From an
  allow-listed sender it is a request: observing records "would have done",
  `auto` starts one lead routine (billing hold and approvals apply). From anyone
  else it is only a candidate for the owner's rules, whatever the mail source
  mode says; `ignore` still drops it.
- No mail server is built. Without a connected inbox plugin the setting is
  inert; the Gmail poller can still route mail to an alias of the owner's
  account.

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
