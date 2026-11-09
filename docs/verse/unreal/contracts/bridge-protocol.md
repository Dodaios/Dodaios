# Contract: app <-> Verse bridge protocol (`verse.bridge/1`)

Owner: integration owner. Implemented by `dodaios/verse_host/bridge.py` +
`dodaios/verse_host/relays/*.py` (backend side) and the `VerseBridge` module
(Unreal side). Builds on `architecture.md` section 5.

Status legend used below: **[E]** exists in the backend today (file reference
given), **[A]** must be added. Every feed names the web Verse consumer it
replaces, so parity can be checked feed by feed.

## 1. Transport

| Topic | Rule |
|---|---|
| Endpoint | `ws://127.0.0.1:<backend port>/api/verse/bridge`, a route of the existing FastAPI app **[A]** (`dodaios/ui/web/verse_routes.py`). No second port |
| Port discovery | The supervisor passes the full URL in `DODAIOS_VERSE_BRIDGE` (for example `ws://127.0.0.1:8765/api/verse/bridge`) and the token in `DODAIOS_VERSE_TOKEN`, both in the child environment, never on the command line. `VerseBridge` reads only these two variables |
| Dev discovery | Editor or standalone runs without a supervisor: when the backend config has `verse.dev_bridge = true` it writes `<DATA_DIR>/verse/bridge.json` `{url, token, pid}` (user-only file ACL, deleted on shutdown). `VerseBridge` falls back to it only in non-Shipping builds |
| Peer check | Loopback peers only (`127.0.0.1`, `::1`), checked before the handshake, also when the backend listens wider for remote mode. Other peers: close `4403` |
| Handshake | First frame from Verse is `hello` (section 3.1) within 5 s. Missing or malformed: close `4400`. Wrong token: close `4401`. Unsupported protocol: close `4426` with `welcome`-shaped reason text naming the supported versions. Same pattern as the mission socket hello (`dodaios/ui/web/missions_ws_routes.py:223-259`) **[E]** |
| Token | 256-bit, random per launch, compared in constant time. A token is valid only while the `Verse.exe` it was minted for is alive |
| One client | A second authenticated connection replaces the first (the first gets close `4409 replaced`) |
| Frames | UTF-8 JSON text frames for everything except terminal cells; binary frames for terminal cells (section 5.4). Max frame 1 MiB; larger: close `1009` |
| Heartbeat | Verse sends `ping` every 1 s; the server answers `pong`. The server treats 5 s without any frame as hung and reports it to the supervisor (restart policy in `architecture.md` 1.1). Verse treats 5 s without any frame as a dead link and reconnects |
| Reconnect | Verse retries with backoff 250 ms, 1 s, 2 s, 4 s, then every 5 s, with the same token. `hello.last_seq` is informational: the server never replays; it sends a fresh snapshot for every topic Verse resubscribes to. Close `4401` on reconnect means the launch is over: Verse saves state and quits |
| Back pressure | One bounded queue per topic on the server. `screens` keeps only the newest frame per pane; `roster`, `panes`, `chat_tails`, `meetings` coalesce deltas into the next snapshot when their queue overflows; events (`progression.awarded`, `lifecycle.*`, `reply`) are never dropped |
| Ordering | Every server frame carries `seq`, one counter per connection, strictly increasing. A delta carries `base` = the `seq` of the snapshot or delta it applies to; Verse that sees a gap requests `resync {topic}` |
| Secrets | Never cross the bridge: no API keys, no credentials, no full chat bodies beyond the tail limits below, no file contents |

## 2. Envelope and versioning

Every JSON frame is one object:

```json
{ "type": "roster.delta", "seq": 4182, "ts": 1793612345.120, "data": { } }
```

| Field | Direction | Meaning |
|---|---|---|
| `type` | both | Message type, `<area>.<verb>`; table in section 8 |
| `seq` | server -> Verse | Per-connection sequence number |
| `ts` | both | Sender's wall clock, epoch seconds (float) |
| `id` | Verse -> server | Request id (`"c-17"`), present on every command; unique per connection |
| `re` | server -> Verse | On `reply`: the `id` it answers |
| `base` | server -> Verse | On deltas: the `seq` the delta applies on top of |
| `data` | both | Payload; schemas below |

| Versioning rule | |
|---|---|
| Protocol id | `verse.bridge/1`. The major number changes only on a breaking change |
| Additive changes | New message types, new optional fields and new enum values are allowed within `/1`. They are announced in `welcome.features` so either side can tell what the other speaks |
| Unknown input | Unknown `type`: ignored (logged once per type). Unknown field: ignored. Unknown enum value in a feed: treated as the documented fallback (`unknown`, `idle`) |
| Breaking change | Goes to `verse.bridge/2`. The backend accepts N and N-1 for at least one app release; `hello.protocols` lists what Verse speaks, `welcome.protocol` names the one picked |
| Build pairing | `welcome.app_version` and `hello.build` are logged on both sides; a mismatch is never fatal by itself |

Replies: every command gets exactly one `reply`.

```json
{ "type": "reply", "seq": 4190, "ts": 1793612345.5, "re": "c-17", "data": { "ok": true, "result": { } } }
{ "type": "reply", "seq": 4191, "ts": 1793612345.6, "re": "c-18", "data": { "ok": false, "error": { "code": "not_found", "message": "Pane is gone." } } }
```

Error codes: `bad_request`, `not_found`, `conflict`, `busy` (a single-flight command is already running, section 14), `unavailable` (feature off or backend part not running), `rate_limited`, `internal`. `message` is English and for logs only; Verse shows its own localised text keyed by `code`.

## 3. Handshake and subscriptions

### 3.1 `hello` (Verse -> server, first frame)

```json
{ "type": "hello", "ts": 1793612340.0, "data": {
  "token": "b64url-43-chars",
  "protocols": ["verse.bridge/1"],
  "build": { "version": "0.1.0", "changelist": "a1b2c3d", "config": "Shipping", "platform": "Win64" },
  "pid": 23144,
  "last_seq": 0,
  "encodings": { "screens": ["cells.bin/1", "cells.json/1"] },
  "capabilities": { "panel_stream": true, "duel": true }
} }
```

### 3.2 `welcome` (server -> Verse)

```json
{ "type": "welcome", "seq": 1, "ts": 1793612340.1, "data": {
  "protocol": "verse.bridge/1",
  "app_version": "4.1.1",
  "app_pid": 9120,
  "session": "vb-3f2c",
  "features": ["roster", "panes", "screens", "chat_tails", "meetings", "groups", "progression", "duel_stats", "companion", "lifecycle", "panel"],
  "encoding": { "screens": "cells.bin/1" },
  "limits": { "screens_max_panes": 8, "screens_max_rows": 60, "screens_max_cols": 240, "screens_max_hz": 10, "chat_tails_max_agents": 6, "chat_tail_lines": 12 },
  "locale": { "lang": "en", "fallback": "en", "strings": { "verse.ranks.duty.working": "On duty" } },
  "settings": { "gore": "full", "reduced_motion": false, "return_key": "F10", "ui_sound": true, "level_sound": true,
                "uniform": "standard", "view": { "mode": "third", "sensitivity": 1.0, "invert_y": false, "fov_third": 70, "fov_first": 85, "quality": "auto", "volume": 0.7 } },
  "decks": ["bridge", "ops", "engineering", "hangar"],
  "state": { "visibility": "visible", "panel": "hidden", "gpu": "free" }
} }
```

| Field | Source | Status |
|---|---|---|
| `locale.strings` | The frontend i18n chunk `ship` for the person's language, read from the same JSON files the web app bundles (5 locales); a string change needs no Unreal rebuild | **[A]** loader in the relay |
| `settings.*` | New `verse.*` keys in the app config (`verse.gore`, `verse.return_key`, `verse.reduced_motion`, `verse.ui_sound`, `verse.level_sound`, `verse.uniform`, `verse.view.*`); changed live with `settings.changed`, written by Verse with `settings.set` (section 14). `settings.game` (additive, feature `game_settings`): the in-game settings menu flat by setting id, from the catalogue `dodaios/verse_host/game_settings.py` (graphics, audio, mouse and camera, keybinds incl. duel FOV and scalability, gameplay, HUD, accessibility; `docs/verse/unreal/game-settings.md`). The app config is their truth; Unreal mirrors them into its user settings file only as a cache | **[A]** |
| `decks` | `VERSE_DECKS` (`dodaios/progression/rules.py:51`) | **[E]** |

### 3.3 `subscribe` / `unsubscribe` / `resync` (Verse -> server)

```json
{ "type": "subscribe", "id": "c-1", "ts": 1793612340.2, "data": { "topics": ["roster", "panes", "progression", "meetings", "groups"] } }
{ "type": "resync", "id": "c-9", "ts": 1793612399.0, "data": { "topic": "roster" } }
```

Each subscribed topic answers with a `<topic>.snapshot` before any delta. `screens` and `chat_tails` take explicit watch lists instead (sections 5.2, 6). Topics not in `welcome.features` reply `unavailable`.

## 4. Roster: agents, panes, ranks, duty status

One topic `roster` carries the crew as the Verse needs it: society agents (officers), coding panes (technicians), each with rank and a **duty status the backend computes**, so Unreal never re-implements the precedence rules.

### 4.1 Sources

| Piece | Backend source | Today's web consumer | Status |
|---|---|---|---|
| Agents | `GET /api/society/agents` (`dodaios/ui/web/society_routes.py:378`): row + `run_state` (`paused`/`waiting`/`working`/`idle`) + `waiting_reason` | `useSocietyRoster` via `life/useCrewLife.ts:57-65` (30 s + invalidation every 5-6.5 s) | **[E]** read; **[A]** relay |
| Panes | `GET /api/agentic-ide/panes` (`dodaios/ui/web/agentic_ide_routes.py:1643`), row shape `WorkspacePaneRow` (`frontend/src/lib/agenticIdeApi.ts:891`) | `crewFeeds/codingFloor.ts` (4 s poll) | **[E]** read; **[A]** relay |
| Push triggers | `SocietyRoomChanged`, `SocietyMessageSent`, `SocietyResultPosted`, `SocietyTeamChanged`, `SocietyCheckpointChanged` (`dodaios/core/events.py:2481-2616`); `AgenticIdePaneActivity`, `AgenticIdeTerminalsAdded`, `AgenticIdeTerminalsClosed`, `AgenticIdeWorkspaceChanged` (`events.py:927-1010`) | `/ws` bus forward (`dodaios/ui/web/server.py:1808`, `subscribe_all` at `:1859`) | **[E]** events; **[A]** relay subscribes |
| Error signal | `SocietyResultPosted.status == "blocked"` | `ranks/useRanks.ts` duty board | **[E]** event; **[A]** relay keeps last status per agent |
| Ranks | `GET /api/progression` subjects (`agent:<id>`, `person`), `RANKS` ladder (`rules.py:185`) | `ranks/ranks.ts` `rankForLevel` | **[E]**; **[A]** relay joins level to rank |
| Duty status | Precedence `paused > waiting > working > error > idle` (`ranks/dutyStatus.ts`) | `ranks/dutyStatus.ts` `dutyOf` and the pane variant | **[A]** Python port `dodaios/verse_host/duty.py` with a parity test against the TS table |

Relay cadence: snapshot on subscribe; re-read agents on any society trigger (coalesced to at most 2 Hz); patch panes in place from `AgenticIdePaneActivity` (its payload is the activity half of a pane row); re-read panes on `TerminalsAdded/Closed/WorkspaceChanged`; safety re-read every 30 s. A delta is sent only when a field Verse sees changed.

### 4.2 `roster.snapshot`

```json
{ "type": "roster.snapshot", "seq": 12, "ts": 1793612340.4, "data": {
  "commander": { "subject_id": "person", "level": 14, "rank": "lieutenant", "title": "Lieutenant", "uniform": "standard" },
  "agents": [
    { "agent_id": "ag_7f1", "name": "Mara", "title": "Research scout", "tier": "specialist",
      "lifecycle": "active", "run_state": "waiting", "waiting_reason": "question",
      "duty": "waiting", "level": 6, "rank": "ensign", "look": "look_02",
      "figure": { "archetype": "engineer", "palette": "graphite" }, "team_ids": ["grp_a"], "pane": null }
  ],
  "panes": [
    { "pane_id": "ws_91:T1", "workspace_id": "ws_91", "key": "T1", "history_id": "h_55", "name": "T1",
      "display_name": "Claude Code", "agent": "claude", "title": "Fix the login retry",
      "status": "live", "activity": "working", "activity_since": 1793612301.0, "worked": true,
      "duty": "working", "workspace_active": true, "cols": 132, "rows": 40 }
  ]
} }
```

| Field | Values | Fallback |
|---|---|---|
| `agents[].duty`, `panes[].duty` | `working`, `waiting`, `idle`, `paused`, `error` (`DUTY_STATUSES`) | `idle` |
| `agents[].run_state` | `paused`, `waiting`, `working`, `idle` | `idle` |
| `agents[].lifecycle` | `active`, `paused` (archived agents are never sent) | `active` |
| `panes[].status` | `pending`, `live`, `exited`, `error` | `pending` |
| `panes[].activity` | `starting`, `working`, `waiting`, `asking`, `failed`, `exited`, `stopped`, `unknown`, `""` (`PaneActivity`) | `unknown` |
| `rank` | ids of `RANK_IDS` (`rules.py:203`) | first rank |
| `pane_id` | `<workspace_id>:<key>`, the same id `/api/agentic-ide/screens` takes | |

Only the fields above cross the bridge; prompts, standing instructions, provider and model settings stay in the app.

### 4.3 `roster.delta`

```json
{ "type": "roster.delta", "seq": 57, "base": 49, "ts": 1793612351.0, "data": {
  "upsert": { "agents": [ { "agent_id": "ag_7f1", "run_state": "working", "duty": "working", "waiting_reason": null } ],
              "panes": [ { "pane_id": "ws_91:T1", "activity": "waiting", "duty": "waiting", "activity_since": 1793612350.8 } ] },
  "remove": { "agents": [], "panes": ["ws_91:T3"] },
  "commander": null
} }
```

Upserts are partial: only `agent_id` / `pane_id` plus the changed fields. An id Verse does not hold arrives complete. `commander` is null when unchanged.

## 5. Terminal screen cells

### 5.1 Sources

| Piece | Backend source | Today's web consumer | Status |
|---|---|---|---|
| Plain screen | `ScreenBuffer` per pane (`dodaios/agentic_ide/screen.py:52`), read by `GET /api/agentic-ide/screens` (`agentic_ide_routes.py:4518`) via `screen_feed.collect_screens`; caps 8 panes, 60 rows, 240 cols (`agentic_ide/screen_feed.py:30-35`) | `crewFeeds/usePaneScreens.ts`, `lib/paneScreensApi.ts` (~450 ms poll) | **[E]** |
| Coloured cells | In-page xterm buffers (`frontend/src/lib/liveTerminals.ts`), painted by `effects/terminalCanvas.ts` | `effects/useScreenFaces.ts`, `effects/ScreensLayer.tsx` | **[E]** in the web page only; cannot cross the process boundary |
| Styled mirror | Attribute-keeping buffer per watched pane, seeded from replay bytes, fed from the PTY output callback as a non-claiming viewer (the PTY socket's `claim=0` bystander mode, `agentic_ide_routes.py:5567`, `:5609`) | none | **[A]** `dodaios/verse_host/relays/screens.py` + `styled_screen.py` |
| Push of dirty rows | none | none | **[A]** |

Fallback: when the styled mirror is not available for a pane (feature flag off, parser error), the relay sends the plain `ScreenBuffer` rows as cells with default colours and `style: "plain"` in the snapshot. Verse draws both the same way.

### 5.2 `screens.watch` (Verse -> server)

Verse names the desks it wants, nearest first; the set replaces the previous one. At most `limits.screens_max_panes` (8) are served; extra ids reply `ok` with `"dropped": [...]`.

```json
{ "type": "screens.watch", "id": "c-30", "ts": 1793612360.0, "data": {
  "panes": [ { "pane_id": "ws_91:T1", "hz": 10 }, { "pane_id": "ws_91:T2", "hz": 2 } ] } }
```

```json
{ "type": "reply", "seq": 80, "re": "c-30", "ts": 1793612360.01, "data": { "ok": true, "result": {
  "bound": [ { "pane_id": "ws_91:T1", "ref": 1 }, { "pane_id": "ws_91:T2", "ref": 2 } ], "dropped": [], "missing": [] } } }
```

`ref` is a small integer the binary frames use instead of the string id; it is valid until the next `screens.watch` reply or reconnect. `hz` is a requested ceiling, 1 to 10 (far desks ask for 2).

### 5.3 Rate and size limits

| Limit | Value |
|---|---|
| Frames per pane | at most `min(hz, 10)` per second, coalesced: rows dirtied in between merge into one frame |
| Total screens bandwidth | 200 KB/s across all panes; above it the relay lowers the rate of the farthest panes first (last in the watch list) |
| Rows / cols | 60 / 240 (larger panes are cut, `cut: true` in the snapshot) |
| Snapshot | On bind, on resize, after `resync {topic: "screens", pane_id}`, and every 30 s as a safety net |
| Idle | A pane without output sends nothing |

### 5.4 Cell format

A cell is `char`, `fg`, `bg`, `attrs`. Rows are sent as runs of cells with the same `fg`, `bg`, `attrs`.

| Element | Encoding |
|---|---|
| `char` | One grapheme cluster (UTF-8). A wide glyph sets `attrs.wide` and covers two columns; the second column is not sent. Empty cells at the end of a row are not sent (Verse clears to the default background) |
| Colour (`fg`, `bg`) | u32: high byte = mode (`0` default, `1` palette index 0-255 in the low byte, `2` RGB in the low 24 bits). JSON form: `null`, `{"i": 9}`, or `"#e3242b"` |
| `attrs` | u16 bit set: 0 bold, 1 dim, 2 italic, 3 underline, 4 inverse, 5 strikethrough, 6 invisible, 7 blink, 8 wide. JSON form: array of names |
| Palette | The 16 base colours are not sent; Verse uses the IDE terminal theme shipped as a DataAsset (same values as the web xterm theme) so screens match the IDE |

**Binary frame `cells.bin/1`** (little endian):

| Offset | Type | Field |
|---|---|---|
| 0 | u8[2] | magic `"VC"` |
| 2 | u8 | format version `1` |
| 3 | u8 | kind: `1` snapshot, `2` delta |
| 4 | u16 | `ref` from `screens.watch` |
| 6 | u32 | `seq` (same counter as JSON frames) |
| 10 | u32 | `base` seq (delta) or `0` (snapshot) |
| 14 | u16 | cols |
| 16 | u16 | rows |
| 18 | i16, i16 | cursor row, col (`-1, -1` = hidden) |
| 22 | u16 | row record count |
| 24 | ... | row records |

Row record: `u16 row`, `u16 run_count`, then runs. Run: `u16 col`, `u16 cells`, `u32 fg`, `u32 bg`, `u16 attrs`, `u16 text_bytes`, `text_bytes` of UTF-8 holding exactly `cells` grapheme clusters (wide glyphs count one cluster, two columns). A row record replaces that row completely. In a snapshot every non-empty row is present and missing rows are blank.

**JSON debug form `cells.json/1`** (tests, harness, and when Verse asks for it in `hello.encodings`):

```json
{ "type": "screens.frame", "seq": 91, "base": 88, "ts": 1793612361.2, "data": {
  "pane_id": "ws_91:T1", "kind": "delta", "cols": 132, "rows": 40, "cursor": [39, 2], "style": "styled",
  "rows_changed": [
    { "row": 38, "runs": [
      { "col": 0, "text": "✔ tests passed", "fg": "#4fb86a", "bg": null, "attrs": ["bold"] },
      { "col": 14, "text": " (42)", "fg": { "i": 8 }, "bg": null, "attrs": [] } ] } ] } }
```

Snapshot extras (JSON form and a companion `screens.meta` text frame sent before each binary snapshot): `{pane_id, ref, cols, rows, style: "styled" | "plain", cut, at}` where `at` is the pane's last output time.

Gone panes: `screens.gone {pane_id, reason: "closed" | "exited" | "not_found"}`.

## 6. Chat tails

| Piece | Backend source | Today's web consumer | Status |
|---|---|---|---|
| Tail read | `GET /api/agent-chat/sessions/{session_id}?tail=60` (`dodaios/ui/web/agent_chat_routes.py`, router prefix `:111`) | `crewFeeds/useDeskChats.ts` (2.5 s + jitter, at most 6 agents), filtered by `crewFeeds/deskChat.ts` `chatLines` | **[E]** read; **[A]** relay + Python port of `chatLines` |
| Push | No agent-chat bus event exists today | | **[A]** relay polls at 2.5 s per watched agent, at most 6 in flight, as today |

```json
{ "type": "chat_tails.watch", "id": "c-41", "ts": 1793612370.0, "data": { "agents": ["ag_7f1", "ag_02c"] } }
```

```json
{ "type": "chat_tails.update", "seq": 120, "ts": 1793612372.6, "data": {
  "agent_id": "ag_7f1", "version": "evt_01J…", "lines": [
    { "kind": "user", "text": "Check the retry window." },
    { "kind": "tool", "text": "Read login.py" },
    { "kind": "agent", "text": "The retry waits 30 s; I changed it to back off." } ] } }
```

`kind`: `user`, `agent`, `tool`, `notice`, `error`. At most 12 lines, each cut on a word boundary at 160 characters (tool 80, notice and error 100, as `deskChat.ts`). Sent only when `version` changes. An agent without a chat session yields `{"agent_id": ..., "lines": [], "version": ""}` once.

## 7. Meetings and groups

| Piece | Backend source | Today's web consumer | Status |
|---|---|---|---|
| Groups | `GET /api/society/chat-groups` (`society_routes.py:754`) | `lib/societyChatGroups.ts` | **[E]** |
| Meeting transcript | `GET /api/society/chat-groups/{id}/meeting` (`society_routes.py:761`, `rt.meetings.snapshot`: `messages`, `running`, `room`) | `crewFeeds/useTeamRounds.ts` (2.4 s tick, 18 s board refresh, 60 s sweep) | **[E]** |
| Team board | `GET /api/society/chat-groups/{id}/team` (`society_routes.py:888`) | `crewFeeds/teamwork.ts` | **[E]** |
| Triggers | `SocietyRoomChanged` (open/settle), `SocietyMessageSent` (room lines), `SocietyTeamChanged` | `/ws` | **[E]**; **[A]** relay |

```json
{ "type": "groups.snapshot", "seq": 14, "ts": 1793612340.5, "data": {
  "groups": [ { "group_id": "grp_a", "name": "Release crew", "members": ["ag_7f1", "ag_02c"], "lead": "ag_02c", "goal": { "goal_id": "g_9", "state": "running" } } ] } }
```

```json
{ "type": "meetings.update", "seq": 133, "ts": 1793612380.0, "data": {
  "group_id": "grp_a", "running": true, "round": 2, "speaker": "ag_02c",
  "room": { "room_id": "room_44", "phase": "open", "topic": "Ship 4.2?", "rounds": 2, "max_rounds": 4 },
  "messages": [ { "id": "evt_01J…", "speaker": "ag_02c", "text": "Tests are green; docs lag." } ] } }
```

`messages` holds the last 8, text cut at 200 characters. `meetings.update` is pushed on every trigger for a group with a running room, and once with `running: false` when it settles (`reason` from `SocietyRoomChanged`). A `groups.delta` follows the roster delta rules.

Commands: `meeting.start {group_id, text}` maps onto `POST /chat-groups/{id}/meeting` (`:770`), `meeting.stop {group_id}` onto `:783`. Both are marked dangerous in the app; the relay asks the app's normal confirmation path and replies `conflict` if the person declines.

## 8. Message catalogue

| Type | Dir | Purpose | Backend status |
|---|---|---|---|
| `hello` / `welcome` | V->S / S->V | Handshake | **[A]** route; pattern **[E]** |
| `ping` / `pong` | V->S / S->V | Heartbeat | **[A]** |
| `subscribe`, `unsubscribe`, `resync` | V->S | Topic control | **[A]** |
| `roster.snapshot`, `roster.delta` | S->V | Section 4 | **[A]** relay over **[E]** sources |
| `screens.watch`, `screens.meta`, `screens.frame` (+ binary), `screens.gone` | both | Section 5 | **[A]** styled mirror + relay |
| `chat_tails.watch`, `chat_tails.update` | both | Section 6 | **[A]** relay over **[E]** read |
| `groups.snapshot`, `groups.delta`, `meetings.update` | S->V | Section 7 | **[A]** relay over **[E]** reads |
| `meeting.start`, `meeting.stop` | V->S | Section 7 | **[E]** backend calls |
| `progression.snapshot`, `progression.awarded`, `progression.action` | both | Section 9 | **[E]** read/event/action; **[A]** relay |
| `duel.result` | V->S | Section 10 | **[A]** rules + stats store |
| `pane.open`, `agent.open`, `ide.focus_terminal`, `agent.create`, `launcher.start` | V->S | Section 11 | mixed, see 11 |
| `lifecycle.*`, `window.*`, `focus.return_to_app`, `panel.*`, `gpu.*`, `settings.changed` | both | Section 12 | **[A]** verse host |
| `agents.open_list`, `group.open`, `simulator.open`, `ide.open`, `launcher.cancel`, `settings.set`, `progression.told`, `qa.exec` | V->S | Section 14 | **[A]** |
| `companion.snapshot`, `companion.update` | S->V | Section 14 | **[A]** relay over **[E]** pet read |
| `reply` | S->V | Command result | **[A]** |
| `log` | V->S | Verse warnings worth keeping in the app log (`level`, `category`, `message`), at most 10/s | **[A]** |

## 9. Progression: read and world actions

| Piece | Backend source | Today's web consumer | Status |
|---|---|---|---|
| Read | `GET /api/progression` (`dodaios/ui/web/progression_routes.py:73`): `subjects`, `pet_id`, `recent`, `latest_seq`, rulebook (`rewards`, `ranks`, `decks`, `looks`, `titles`) | `progression/progressionStore.ts`, `progressionApi.ts:147`, `ranks/useRanks.ts` | **[E]** |
| Awards | `ProgressionAwarded` (`events.py:2590`) | `/ws` -> progression store, `ranks/PromotionNotice.tsx` | **[E]** |
| World actions | `POST /api/progression/actions` `{action, ref}` (`progression_routes.py:100`), validated against `WORLD_ACTIONS` (`rules.py:152`); 422 on unknown | `progressionApi.ts:179` `reportWorldAction` | **[E]** |

```json
{ "type": "progression.snapshot", "seq": 15, "ts": 1793612340.6, "data": {
  "subjects": [ { "subject_id": "person", "kind": "person", "level": 14, "total_xp": 5230, "into_level": 130, "for_next": 600, "title": "Lieutenant" } ],
  "pet_id": "drone", "latest_seq": 902, "told_seq": 897,
  "rulebook": { "ranks": [ { "id": "recruit", "level": 1, "tier": "enlisted" } ], "rewards": [], "looks": [], "titles": {} },
  "duel_stats": { "matches": 12, "wins": 7, "losses": 5, "kills": 96, "deaths": 81, "headshots": 31, "finishers": 4, "best_streak": 6, "by_tier": { "hard": { "wins": 5, "losses": 3 } } }
} }
```

```json
{ "type": "progression.awarded", "seq": 140, "ts": 1793612390.0, "data": {
  "seq": 903, "subject_id": "person", "subject_kind": "person", "xp_source": "duel_won", "xp": 40,
  "total_xp": 5270, "level": 14, "previous_level": 14, "title": "Lieutenant", "unlocked": [], "unlocked_looks": [] } }
```

`progression.awarded.data` is the `ProgressionAwarded` event as it is, so the relay forwards it field for field.

World action (Verse -> server):

```json
{ "type": "progression.action", "id": "c-52", "ts": 1793612395.0, "data": { "action": "inspection", "ref": "hangar" } }
```

| `action` | `ref` | Who reports it in Unreal | Rule today (`rules.py:131-146`) |
|---|---|---|---|
| `daily_visit` | ignored, the server uses its own day (`progression/service.py:182`) | `VerseDecks`, on the first Visible state of a launch | 25 XP, once per day |
| `deck_discovered` | deck id from `VERSE_DECKS` | `VerseDecks`, first arrival on a deck | 20 XP, once per deck |
| `inspection` | deck id | `VerseDecks`, every room of the deck visited (port of `life/useWorldActions.ts`) | 15 XP, once per deck, cap 30/day |
| `walk_together` | `""` | `VerseCrew`, every 50 m with the drone within 2.5 m | pet 3 XP, cooldown 20 s, cap 60/day |
| `team_briefing` | team (group) id | `VerseCrew`, a team round running while the commander is on the bridge | 10 XP, cooldown 600 s, cap 40/day |
| `simulator_round` | game id | `VerseUI` simulator | 8 XP, cooldown 45 s, cap 80/day |
| `simulator_record` | game id (`"asteroid-run"` today, `hud/SimulatorPanel.tsx:39`) | `VerseUI` simulator | 15 XP, cooldown 45 s, cap 60/day |

Reply: `{"ok": true, "result": {"awarded": <award or null>}}` (null when a cap or cooldown ate it). Reporting twice is harmless; the server meters. `duel_won` and `duel_lost` are not world actions and are refused here (`bad_request`); they go through `duel.result`.

## 10. Duel result and stats

Today no XP rule mentions a duel and the duel reports nothing (`dodaios/progression/rules.py:131-146`). Everything in this section is **[A]**.

One `duel.result` per set (`contracts/combat-state.md` 9.1): each finished
set (first to 10 kills) sends one with `outcome` `won` or `lost`; leaving the
arena mid-set, or Verse quitting, sends the unfinished set with `outcome`
`unfinished`. The payload is `FVerseSetSummary` (`contracts/combat-state.md`
11.1) field for field.

```json
{ "type": "duel.result", "id": "c-60", "ts": 1793612500.0, "data": {
  "match_id": "m_01JD…", "session_id": "s_01JD…", "set_index": 3, "mode": "deathmatch_1v1", "ruleset": "endless/1",
  "opponent": { "kind": "bot", "tier": "hard", "adaptive": false },
  "started_at": 1793612200.0, "ended_at": 1793612500.0, "match_time_s": 296.4, "end_reason": "set_complete",
  "outcome": "won",
  "score": { "player": 10, "opponent": 7 },
  "stats": { "kills": 10, "deaths": 7, "headshots": 4, "finishers": 1, "melee_kills": 1,
             "shots_fired": 540, "shots_hit": 201, "damage_dealt": 2760, "damage_taken": 2210,
             "walls_breached": 2, "bulwarks_placed": 3, "best_streak": 4 },
  "weapons": [ { "weapon_id": "graveline", "kills": 8, "headshots": 4, "shots_fired": 410, "shots_hit": 152 } ],
  "build": { "version": "0.1.0", "changelist": "a1b2c3d" }
} }
```

| Field | Rule |
|---|---|
| `match_id` | Unique per result (one set); a second `duel.result` with the same id replies `ok` with the first result (idempotent) |
| `session_id`, `set_index` | The arena session the set belongs to and its 1-based index in it |
| `mode` / `ruleset` | From the swappable game mode (`UVerseRuleset`); only `deathmatch_1v1` pays XP in `/1` |
| `outcome` | `won`, `lost` (finished set) or `unfinished` (the person left or Verse quit mid-set). A `won` or `lost` set with `match_time_s` under 60 pays no XP; `unfinished` never pays XP. Every result counts in the statistics |
| `end_reason` | `set_complete`, `player_left`, `verse_quit`, `crash_recovered` (sent on the next launch from the saved pending result), `app_quit` |
| `match_time_s` | Match time of the set, paused time excluded |
| `stats` | Integers, non-negative; the server clamps implausible values (more than 1 kill per 2 s of match time) and logs them |
| `weapons[].weapon_id` | Ids from the weapon DataAsset (fictional names only) |

Backend additions:

| Addition | Where | What |
|---|---|---|
| XP rules | `dodaios/progression/rules.py` `RULES` | `XpRule("duel_won", "person", 40, "server", daily_cap=200)`, `XpRule("duel_lost", "person", 10, "server", daily_cap=50)`, `XpRule("duel_finisher", "person", 5, "server", daily_cap=25)` (per finisher in a paying set). Tier multiplier on `duel_won`: normal 1.0, hard 1.5, elite 2.0, adaptive 1.5. Trigger `server`, so `POST /actions` cannot pay them. Numbers are a starting point owned by the progression owner; changing them is not a protocol change |
| Frontend parity | `tests/unit/progression/test_frontend_parity.py` | Covers the new sources the web ranks code lists |
| Stats store | `dodaios/progression/duel_stats.py` (new table next to the progression ledger) | One row per result + running totals: sets, wins, losses, unfinished, kills, deaths, K/D, headshots, finishers, best streak, per tier and per weapon |
| Read | `GET /api/progression` gains `duel_stats` (totals); `GET /api/progression/duels?limit=20` lists recent matches | For the web service record (`ranks/ServiceRecord.tsx`) and the Unreal one |
| Service | `ProgressionService.record_duel(result)` | Stores the row, pays rules, publishes `ProgressionAwarded` per award (existing path) and a new `VerseDuelRecorded {match_id, outcome, kills, deaths}` bus event |

Reply:

```json
{ "type": "reply", "seq": 171, "re": "c-60", "ts": 1793612500.2, "data": { "ok": true, "result": {
  "recorded": true, "awards": [ { "xp_source": "duel_won", "xp": 60 } ], "duel_stats": { "matches": 13, "wins": 8 } } } }
```

## 11. Station commands

| Command | Args | Backend action | Status |
|---|---|---|---|
| `pane.open` | `{pane_id, open?: "changes"}` | New bus event `VerseOpenRequested {target: "pane", workspace_id, name}`; the web UI runs the same code as `crewFeeds/codingNavigate.ts` `openPaneSession` (IDE section, pane maximised, side panel un-maximised); the desktop process raises the app window. Verse hides itself (`lifecycle.hidden` follows) | **[A]** event + web handler; open logic **[E]** |
| `agent.open` | `{agent_id}` | `VerseOpenRequested {target: "agent", agent_id}`; web UI opens the agent card, as `VerseStage.tsx:332-337` `openCrew` | **[A]** event + handler |
| `ide.focus_terminal` | `{pane_id}` | Desk takeover. Same as `pane.open` but the pane gets keyboard focus at once (the web Verse's `hud/TakeoverPanel.tsx` moves the DOM; Unreal never hosts a live terminal) | **[A]** |
| `agent.create` | `{name?, title?, figure?}` | Same code as `POST /api/society/agents` (`society_routes.py:434`); reply carries `{agent_id}`; the new agent then arrives in `roster.delta` | **[E]** backend; **[A]** relay call |
| `launcher.start` | `{workspace_id?, agents: [{agent, count}], brief}` | Same sequence the web launcher runs (`hud/LauncherPanel.tsx`): `POST /api/agentic-ide/terminals` (`openTerminal`), `.../terminals/{name}/start`, `.../terminals/{name}/prompt` with the brief. Reply lists the created `pane_id`s and per pane `submitted` (the honest three-way answer, as `AgenticIdePromptSent`) | **[E]** endpoints; **[A]** relay moves the sequence into the backend so both callers share it |
| `launcher.options` | `{}` | Reads `GET /api/agentic-ide/state` and the IDE agent list (`fetchIdeState`, `fetchIdeAgents`); reply `{workspaces, agents}` for the station UI | **[E]** reads; **[A]** relay |

```json
{ "type": "launcher.start", "id": "c-71", "ts": 1793612600.0, "data": {
  "workspace_id": "ws_91", "agents": [ { "agent": "claude", "count": 2 } ], "brief": "Write the bridge relay tests." } }
```

```json
{ "type": "reply", "seq": 190, "re": "c-71", "ts": 1793612603.4, "data": { "ok": true, "result": {
  "panes": [ { "pane_id": "ws_91:T4", "submitted": true }, { "pane_id": "ws_91:T5", "submitted": null } ] } } }
```

Rate limits: `agent.create` 1 per 5 s, `launcher.start` 1 per 10 s, open commands 4/s; above that `rate_limited`.

## 12. Lifecycle, window and panel

State machine as `architecture.md` 1.3: `Booting`, `Visible`, `Panel`, `Dormant`, `Exiting`.

Server -> Verse:

| Type | Data | Verse does |
|---|---|---|
| `lifecycle.show` | `{monitor: {x, y, w, h, dpi}, reason: "verse_view" \| "quick_start_duel" \| "station"}` | Sent after the desktop process called `AllowSetForegroundWindow(verse_pid)`. Show window, take focus, resume. `quick_start_duel` goes straight to the arena |
| `lifecycle.hide` | `{reason: "app_focus" \| "user" \| "minimised"}` | Hide window, pause the match, stop rendering, mute; go Dormant (or Panel if the panel streams) |
| `lifecycle.pause` / `lifecycle.resume` | `{reason}` | Pause or resume simulation and audio without changing the window (system dialogs, screen lock) |
| `lifecycle.quit` | `{reason: "app_quit" \| "idle_10min" \| "gpu_pressure" \| "update", deadline_ms: 3000}` | Save match-free state, send any pending `duel.result`, reply `lifecycle.bye`, exit before the deadline; the job object kills it after |
| `panel.visibility` | `{visible: bool, w, h, dpr}` | The IDE side panel became visible or hidden (`IntersectionObserver` + page visibility in `OfficeTab.tsx`). Visible and no full view: enter Panel, start the Pixel Streaming session. Hidden: stop within 1 s |
| `panel.resize` | `{w, h, dpr}` | Resize the offscreen panel target |
| `gpu.yield` / `gpu.free` | `{by: "blender_cook" \| "local_stt" \| "local_model" \| "other"}` | Dormant: quit at once. Visible: drop to Low scalability until `gpu.free` |
| `settings.changed` | `{gore?, return_key?, reduced_motion?, lang?, strings?, view?, game?}` | Apply live; `game` holds only the changed setting ids |
| `focus.app_took` | `{}` | The app came to the front by itself (alt-tab, click); same as `lifecycle.hide {reason: "app_focus"}` |

Verse -> server:

| Type | Data | Server does |
|---|---|---|
| `lifecycle.state` | `{state, vram_mb, fps}` | On every state change; feeds `GET /api/verse/status` and the launcher card |
| `lifecycle.ready` | `{first_frame_ms}` | After the first frame; the supervisor marks the launch healthy |
| `focus.return_to_app` | `{reason: "return_key" \| "station" \| "esc_menu"}` | Verse has called `AllowSetForegroundWindow(app_pid)` and hidden itself; the desktop process raises the app window |
| `window.state` | `{visible, minimised, monitor}` | Keeps the host in sync after OS-driven changes |
| `panel.stream_state` | `{state: "starting" \| "streaming" \| "stopped" \| "failed", error?}` | The panel shows the stream, the last frame with "Verse is open", or the fallback card |
| `lifecycle.bye` | `{saved: bool}` | Answer to `lifecycle.quit` |

On Linux Wayland, `lifecycle.show` and `focus.return_to_app` carry `activation_token` (`xdg-activation`), per `architecture.md` 1.2.

## 13. Backend work list

| # | Piece | Path | Status |
|---|---|---|---|
| BW1 | Route, loopback check, hello, one-client rule, heartbeat | `dodaios/ui/web/verse_routes.py`, `dodaios/verse_host/bridge.py` | **[A]** |
| BW2 | Supervisor env (`DODAIOS_VERSE_BRIDGE`, `DODAIOS_VERSE_TOKEN`), dev `bridge.json` | `dodaios/verse_host/supervisor.py` | **[A]** |
| BW3 | Roster relay with duty port and rank join | `relays/roster.py`, `verse_host/duty.py` | **[A]** over **[E]** reads/events |
| BW4 | Styled screen mirror + screens relay + binary codec | `relays/screens.py`, `verse_host/styled_screen.py`, `verse_host/cells_codec.py` | **[A]** |
| BW5 | Chat tail relay with `chatLines` port | `relays/chat_tails.py` | **[A]** over **[E]** read |
| BW6 | Groups and meetings relay | `relays/meetings.py` | **[A]** over **[E]** reads/events |
| BW7 | Progression relay (snapshot, awarded forward, actions) | `relays/progression.py` | **[A]** over **[E]** |
| BW8 | Duel rules, stats store, `record_duel`, `GET /api/progression/duels`, `VerseDuelRecorded` | `dodaios/progression/*`, `core/events.py` | **[A]** |
| BW9 | `VerseOpenRequested` bus event + web handler, launcher sequence moved into the backend | `core/events.py`, `frontend/src/hooks/useWebSocket.ts`, `dodaios/agentic_ide/` | **[A]** |
| BW10 | Locale and `verse.*` settings in `welcome` and `settings.changed` | `relays/settings.py` | **[A]** |
| BW11 | Contract tests: golden JSON for every message here, binary codec round trip, parity tests duty/chatLines vs TS. The golden fixtures and `scripts/unreal/fake_bridge.py` exist from G0 (`work-packages.md` G0.11) | `tests/unit/verse_host/fixtures/`, `scripts/unreal/fake_bridge.py` | **[A]** |
| BW12 | Section 14 additions: open commands, launcher single flight, `settings.set` and the settings import route, `told_seq`, `companion` topic, `qa.exec` | `relays/*.py`, `dodaios/ui/web/verse_routes.py` | **[A]** |

The `BW` prefix keeps these items apart from the bot invariants B1-B8 of
`contracts/bot.md`.

## 14. Parity additions

These close the gaps `parity.md` section 20 found. They are part of
`verse.bridge/1` from the first freeze, so no package waits on a contract
change for them.

| Message | Dir | Data | Backend action | Parity rows |
|---|---|---|---|---|
| `agents.open_list` | V->S | `{}` | `VerseOpenRequested {target: "agents"}`: the web UI opens the Agents ledger (side panel Agents tab); Verse hides | S-02 |
| `group.open` | V->S | `{group_id}` | `VerseOpenRequested {target: "group", group_id}`; `not_found` when the group is gone | S-03 |
| `simulator.open` | V->S | `{programme}` | `VerseOpenRequested {target: "simulator", programme}`: the web arcade (`src/components/society/arcade/*`) opens and reports its own `simulator_round` / `simulator_record` actions | S-07, W-06 |
| `ide.open` | V->S | `{}` | `VerseOpenRequested {target: "ide"}`: the IDE section without a pane | X-06 |
| `launcher.start` (rule) | V->S | as section 11 | Single flight: while a batch runs, a second `launcher.start` replies `busy` | X-04 |
| `launcher.cancel` | V->S | `{}` | Stops starting further panes of the running batch; panes already open stay; reply `{stopped: n}` | X-04 |
| `pane.open` `open: "changes"` | V->S | `{pane_id, open: "changes"}` | The web handler opens the pane's changes view (`requestPane(..., {open: "changes"})`) | X-08 |
| `progression.told` | V->S | `{seq}` | Stores the highest award seq Verse has shown to the person; `progression.snapshot.told_seq` carries it, so a level-up shown once is not shown again | F-13 |
| `companion.snapshot`, `companion.update` | S->V | `{pet_id, look, style}` | Topic `companion` from the active pet read (`companionPetStore` source) and the overlay style; an update within 2 s of a change | F-14 |
| `settings.set` | V->S | any subset of `welcome.settings` | Validates and writes the `verse.*` config keys, then sends `settings.changed` with the result to Verse (and to the web UI through the bus). Unknown keys: `bad_request` | F-18, R-12, V-21, T-01, T-04, Z-14 |
| `qa.exec` | V->S, S->V | `{command, args}` / reply `{result}` | Runs a `Verse.QA.*` console command in a Shipping build. The backend forwards it only when it runs with `DODAIOS_VERSE_QA=1`; otherwise every `qa.exec` replies `unavailable` | Q-01..Q-12 |

`POST /api/verse/settings/import` (REST, web app to backend, once): the web
app posts the browser-stored values `dodaios.verse.view.v1`,
`dodaios.verse.uniform.v1`, `jarvis.verse.level.sound.v1`,
`jarvis.verse.levels.seen.v1` and `jarvis.office.arcade.asteroids.best`; the
backend writes the matching `verse.*` keys and `told_seq` only where they are
still unset, and answers `{imported: [...]}`. A second call imports nothing.

## Frozen interface

Other packages may rely on exactly this:

1. Transport: one WebSocket at `/api/verse/bridge` on the backend port, URL and token from `DODAIOS_VERSE_BRIDGE` / `DODAIOS_VERSE_TOKEN`, loopback only, `hello` first, close codes `4400`, `4401`, `4403`, `4409`, `4426`, 1 s ping, 5 s dead-link rule, snapshot-on-reconnect (no replay).
2. The envelope (`type`, `seq`, `ts`, `id`, `re`, `base`, `data`) and the `reply` shape with its error codes.
3. Every message type in section 8 with the fields shown in its example, their meaning and their enum values with fallbacks.
4. `pane_id = <workspace_id>:<key>`, `agent_id` as the society roster's id, `subject_id` as the progression store's id.
5. Duty status is computed by the backend; values `working`, `waiting`, `idle`, `paused`, `error`.
6. The cell model (`char`, `fg`, `bg`, `attrs`), the colour and attribute encodings, the `cells.bin/1` layout, the `cells.json/1` form, and the limits 8 panes / 60 rows / 240 cols / 10 Hz / 200 KB/s.
7. The world action list and `ref` meanings in section 9, and that `duel_*` XP only comes through `duel.result`.
8. The `duel.result` schema and its idempotency on `match_id`.
9. Lifecycle and panel messages in section 12 and their mapping onto the states in `architecture.md` 1.3.
10. The section 14 messages, their data, the `busy` error code and the settings import route.
11. One `duel.result` per set with `outcome` `won`, `lost` or `unfinished` (section 10).

Not frozen: XP amounts and caps, relay cadences inside the stated ceilings, internal backend file layout, log text.

## Change rule

Changes to this contract go through the integration owner only. A work package that needs a change opens a request against `docs/verse/unreal/contracts/` naming the message, the reason and both consumers; the integration owner updates this file, the golden test fixtures (BW11) and the `VerseBridge` codec in one pull request. Additive changes stay in `verse.bridge/1` and are announced in `welcome.features`; anything that renames, removes or changes the meaning of a field, an enum value or a binary offset is `verse.bridge/2` and keeps `/1` served for one app release.
