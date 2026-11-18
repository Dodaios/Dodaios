# Node live build

When an agent creates or edits a node, the person watches it being built
beside the conversation. The node window opens by itself, the type's skeleton
shows while its editor loads, and every edit plays in with the agent's
presence: a cursor, a name tag, and a frame around what is being written.

This page is the contract for the shared core and for each type's own reveal.

## Flow

1. The agent calls the `node`, `whiteboard` or `clip` tool. The tool names the
   author with `live.writing(await live.author_for(session_id))`.
2. `NodeStore` writes the node and calls `live.changed(...)`
   (`dodaios/nodes/live.py`). That publishes one `NodeChanged` event on the
   app bus. The WebSocket forwards it to every window.
3. `hooks/useWebSocket.ts` hands the event to `receiveNodeChange`
   (`components/nodes/live/receive.ts`). It updates the live store and the
   node's watcher query (`["node-upkeep", slug]`). An open page reloads and an
   open editor fetches the new spec at once. Polling stays as the fallback
   (20 s while the socket is up, 5 s while it is down).
4. The chat card (`PageCard`) shows "being built" while the agent's turn runs.
   If its conversation is on screen, the card opens the node window by itself
   (`live/autoOpen.ts`).
5. The editor takes the revision (`useNodeSpecEditor`, `remote`). The
   `LiveBuildLayer` in `EditorShell` asks the type's adapter for reveal steps
   and the player plays them.

## The event

`NodeChanged` (`dodaios/core/events.py`). The WebSocket envelope has
`event_name: "NodeChanged"` and this payload:

| Field | Meaning |
|-------|---------|
| `node_id` | The node id (12 hex characters). |
| `ref` | `slug::page_path`: the address the stage, the chat card and the node window use. |
| `slug` | The node's run directory. |
| `node_type` | `docs`, `slides`, `sheets`, `data`, `whiteboard` or `motion`. |
| `title` | The node's title after the write. |
| `version`, `previous_version` | The version after the write and the version it was made from (0 for a create). |
| `updated_at` | Seconds since the epoch, as `/api/nodes` reports it. |
| `action` | `create`, `update`, `revert`, or `save` (the person's editor). |
| `rewrite` | `true` when the spec was replaced whole. `ops` is then empty. |
| `ops` | The `changes` the call applied, in order: `{op, path, value?, to?, find?}`. A value over 4000 characters of JSON is `null` with `value_omitted: true`. More than 120 ops are sent as a rewrite. |
| `author_kind` | `assistant` (the lead, a named agent, a coding thread) or `person`. |
| `author_name` | The name on the tag: the assistant's name, a named agent's name, or the coding agent's name. |
| `author_id` | Tells authors apart: `lead`, `agent:<id>`, `thread:<session id>`, `person`. |
| `session_id` | The chat session the call came from, or `""`. |
| `step` | The agent's current step when known, else `""`. Reserved: the backend sends `""` today. |

A write that no tool named is the person's: a rename, Undo in the library, an
editor's save. A person's write never starts a playback or shows presence.

## The reveal adapter

Every type has one file: `components/nodes/live/adapters/<type>.ts`. Until a
type's own reveal lands, the file exports `defaultReveal`. Change only that
file and the type's editor.

```ts
interface RevealInput<S> {
  type: NodeType;
  previous: S | null;      // the spec before; null when the editor opened mid-build
  next: S;                 // the spec the editor shows now (already drawn in root)
  ops: LiveOp[] | null;    // the agent's ops in order; null for a rewrite or an unknown range
  initial: boolean;        // the editor opened while the agent was building
  root: HTMLElement;       // the editor's body; read it, never change it
}

interface RevealStep {
  target: RevealTarget;
  label?: string;          // the status while this step plays
}

interface RevealAdapter<S> {
  steps(input: RevealInput<S>): RevealStep[];   // in the order they play
}
```

`steps` runs after the body shows `next`. If it returns no units, the core
asks once more after `settleWaitMs`.

### How a step names its target

| Target | Resolves to |
|--------|-------------|
| `{ path: "/rows/3" }` | The element with `data-live-path="/rows/3"`. If there is none, the nearest marked parent path (`/rows/3/2` falls back to `/rows/3`, then `/rows`). |
| `{ selector: ".cell-a1" }` | The first match inside the body. |
| `{ element }` | An element the adapter found itself. |
| `{ changed: true }` | What the core saw change in the body's DOM for this batch, one step per changed block, in reading order. This is the default. |
| `{ blocks: true }` | The body's top-level blocks, in reading order. The default when the editor opened mid-build. |

A step whose target is not found is skipped.

A step may set `framed: false` to play without growing the presence frame (a
new tab in a tab bar). An adapter may set `tagCorner: "bottom"` to put the name
tag on the frame's lower-left corner (default: top-left).

To use `path` targets, add `data-live-path="<JSON Pointer>"` to the elements
that draw spec items.

### Where each type plugs in

| Type | Adapter | Editor |
|------|---------|--------|
| docs | `adapters/docs.ts` | `editors/docs` (draws in a text editor after React; late DOM changes still join the batch) |
| slides | `adapters/slides.ts` | `editors/slides` |
| sheets | `adapters/sheets.ts` | `editors/sheets` |
| data (Analytics) | `adapters/data.ts` | `editors/data` |
| motion (Clips) | `adapters/motion.ts` | `editors/motion` |
| whiteboard | `adapters/whiteboard.ts` | `whiteboard/WhiteboardEditor`. It is not on `EditorShell` and still plays its own `canvas/liveBuild.ts`. Moving it onto the shared presence means mounting `LivePresence` with a `LivePlayer` over the canvas. |

## Presence and tokens

`LivePresence.tsx` draws the pieces and `LivePlayer` (`playback.ts`) moves
them. The look is black and white, from tokens in `src/index.css` for both
themes:

| Token | Light | Dark | Used for |
|-------|-------|------|----------|
| `--presence-ink` | near-black | near-white | cursor fill, frame, tag ground |
| `--presence-on-ink` | near-white | near-black | tag text, cursor rim |
| `--presence-frame-alpha` | 0.55 | 0.6 | the frame's strength |
| `--presence-pill-bg`, `--presence-pill-ink` | | | the status pill |
| `--presence-skeleton`, `--presence-skeleton-sheen` | | | skeleton blocks and their shimmer |

When two or more agents build at once, `presenceTint` gives each one a muted
tint. A single agent is always the plain ink. Do not use gold, hues or glow.

## Timings

`LIVE_TIMING` in `playback.ts`:

| Name | Value | Meaning |
|------|-------|---------|
| `fadeMs` | 220 | One unit fades from `fromOpacity` (0.3) to full. |
| `staggerMs` | 90 | From one unit's start to the next. |
| `maxBatchMs` | 3000 | A batch never plays longer. Long batches are compressed. |
| `maxUnits` | 60 | More units are revealed in groups. |
| `settleWaitMs` | 160 | The wait before a retry, and before opening mid-build. |
| `captureMs` | 700 | DOM changes this long after the batch started still join it. |
| `openSlideMs` | 150 | The node window sliding in. |

Presence fades `PRESENCE_LINGER_MS` (1.5 s) after the agent's turn ends. A
build with no agent write for `IDLE_SETTLE_MS` (90 s) ends anyway.

## Interruption and the person

- Typing, a click into the content, the wheel or a touch in the body finishes
  the playback at once. The view then stops following the writing until the
  build ends.
- The view follows the writing (`scrollIntoView`, nearest) only until then.
- With `prefers-reduced-motion`, the batch shows at once. Only the presence
  moves.
- An editor with unsaved work goes to "conflict" as before. Nothing plays.
- The window opens by itself only from a card that is on screen, and only on
  an agent's create in the last 30 s. It never takes focus and never opens
  twice for one node. It never replaces a window the person opened. If the
  person closes it, it stays closed for the rest of that turn. A second node
  from the same turn swaps in. Settings > Behavior > "Open nodes as they are
  built" turns it off (`lib/nodeAutoOpen.ts`).

## Agents write in steps

The `node` tool's guide for docs, slides, sheets and data ends with
`BUILD_IN_STEPS` (`dodaios/plugins/tool/node.py`). The agent creates the node
with its title and a skeleton spec, then fills it with several `update` calls
with `changes`, in reading order. Each call is one batch. The playback only
smooths each step.

## Testing a reveal by hand

1. Load the pull request in the Dev app: `python scripts/dev_preview.py <PR>`
   (docs/dev-preview.md).
2. In the Dev app's lead chat, ask for a node of the type, for example "Make
   me a sheet of my monthly costs". The window should open beside the chat,
   show the skeleton, then play each edit in with the presence.
3. Check both themes (Settings > Appearance). The presence must be white on
   charcoal and near-black on paper.
4. Click into the content while a batch plays. It must finish at once, and
   the view must not scroll by itself after that.
5. Turn on reduced motion in the OS. The content must appear at once, with
   the presence only.
6. Unit tests: `npx vitest run src/components/nodes/live` and
   `pytest tests/unit/nodes/test_live.py`.
