# verse.bridge/1 golden fixtures (G0.11)

Golden data for `docs/verse/unreal/contracts/bridge-protocol.md`. The Unreal
automation tests read this folder; the backend pytest reads its mirror in
`tests/unit/verse_host/fixtures/bridge/`. Both copies hold the same files,
and `python scripts/unreal/bridge_schema.py` fails when they drift
(`--sync` copies this folder to the mirror). Change a fixture here, then sync.

| Path | Holds |
|---|---|
| `verse.bridge.1.schema.json` | JSON Schema 2020-12. `x-messages` lists every message type: direction, kind (`handshake`, `command`, `notice`, `feed`, `event`, `reply`), topic, and the `$defs` of its frame, data and reply result. `x-fallback` on an enum names the value a live reader uses for an unknown one |
| `messages/<type>.json` | Golden frames of one type. The first one is the contract's own example |
| `replies/<command>.json` | `{request, reply}` pairs with success and error answers. `request_invalid` marks a malformed request the server answers with `bad_request` |
| `cells/vectors.json` | `cells.bin/1` vectors: a `screens.frame` in `cells.json/1` form, its `ref`, and the exact bytes as hex; plus malformed frames a decoder must reject |
| `scenarios/<name>.json` | Scripted runs of `scripts/unreal/fake_bridge.py`: roster churn, busy panes, meetings, awards, lifecycle, panel, idle |

Golden data is strict: no unknown fields, no unknown enum values. A scenario
step marked `lenient` is off contract on purpose (an unknown duty value, for
example) so readers can prove their fallback.

## Points the contract leaves open, as fixed here

| Point | Fixed as |
|---|---|
| Commands and notices | Verse frames that carry `id` and get one `reply`: every row of section 8 that asks the server to do or answer something. `hello`, `ping`, `log`, `lifecycle.state`, `lifecycle.ready`, `lifecycle.bye`, `window.state`, `panel.stream_state` and `focus.return_to_app` are notices without `id` |
| Reply results the contract does not show | `subscribe` `{subscribed, unavailable}` (error `unavailable` only when no topic is served), `unsubscribe` `{unsubscribed}`, `chat_tails.watch` `{watching, dropped}`, `progression.told` `{told_seq}`, `settings.set` `{settings}` (all values after the write), `launcher.options` `{workspaces, agents}`, `qa.exec` `{result}`; every other command `{}` unless section 11 or 14 names a result |
| `ping`, `pong` | `data` is `{}` |
| `groups.delta` | `{upsert: {groups: [...]}, remove: {groups: [ids]}}`, partial rows as in `roster.delta` |
| `screens.frame` snapshot | Uses `rows_changed` like a delta, carries `ref`, `cut`, `at` and no `base`; a hidden cursor is `[-1, -1]` in JSON as in binary |
| Topics without a snapshot | `panes` (carried by `roster`), `duel_stats` (in `progression.snapshot`), `lifecycle`, `panel`: subscribing replies `ok` and sends nothing; their events are sent without a subscription |
| Wire spelling of states | `lifecycle.state.state` is `booting`, `visible`, `panel`, `dormant`, `exiting`; `welcome.state.gpu` is `free` or `yield` |
| Grapheme clusters | Combining marks, zero-width joiner sequences, variation selectors, skin-tone modifiers and tag characters extend a cluster (`scripts/unreal/bridge_cells.py`) |
