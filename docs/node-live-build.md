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
  lateJoin?: boolean;      // DOM changes just after the batch started join it (docs only)
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

A step may set `visible: true` when its elements are already on screen (a moved
element, a thumbnail that glides): the player does not hide or fade them, the
frame and cursor only visit them. `solo: true` puts the frame on that step's
elements alone instead of growing around everything written. An `{ element }`
target may sit inside a shadow root of the body (the slide canvas does).

A step may set `framed: false` to play without growing the presence frame (a
new tab in a tab bar).

An adapter sets `lateJoin: true` only when its editor draws after React's
commit (the docs text editor): then DOM changes in the body within
`captureMs` of the batch start join it as units. Every other type leaves it
off. There such changes are the editor's own chrome (the Clips time readout,
a ruler, a counter), and the frame and cursor would jump to them.

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
| whiteboard | `adapters/whiteboard.ts` | `whiteboard/WhiteboardEditor`. It is not on `EditorShell`: `canvas/BoardPresence.tsx` mounts `LivePresence` and a `LivePlayer` over the canvas, with one invisible marker per piece (`data-live-path="/elements/<first id>"`) that follows the canvas's scroll and zoom. `canvas/liveBuild.ts` plans the pieces (frames, then shapes with their labels, then arrows) and lands them on the canvas on `revealDelays`; the adapter turns the plan into steps. |

## Presence and tokens

`LivePresence.tsx` draws the pieces and `LivePlayer` (`playback.ts`) moves
them. They are the ones a colleague's cursor has in a shared document:

- **The cursor** is the agent's arrow, the same as over its browser
  (`components/society/card/AgentArrow.tsx`): a rounded arrowhead without a
  tail, dark with a white rim, under a soft glow in the app's signal colour
  (`--accent`). It arrives out of a soft blur. It leans with its speed as it
  travels (up to `LEAN_MAX_DEG`). After a move of `RING_AFTER_PX` or more, a
  ring opens in the glow's colour where it lands. When the agent starts to
  think, it gives one small shake. Reduced motion drops all four.
  While text is written at a caret it stays at the caret. Otherwise it rests
  at the end of the last line written, or at the lower right corner of a
  picture, chart or shape. An editor's controls inside a block ("Add row")
  and a chart's axis labels are not its text. The cursor moves with an
  exponential ease-out that is re-aimed every frame (`CARET_EASE_MS`,
  `HOP_EASE_MS`), so it keeps up with a caret that moves every few
  milliseconds. When the element it rests on scrolls, the cursor moves with it.
- **The name tag** hangs under the tip, dark with white words. The corner
  nearest the arrow is drawn sharp, like a speech bubble's. Near the right or
  bottom edge it moves to the left or above, and the sharp corner moves with
  it. Between
  edits, after `THINKING_AFTER_MS` of quiet, the tag shows the status instead
  of the name ("Dodaios is working…", on a whiteboard "Dodaios is drawing"),
  with a slow sheen over the words. There is no separate status pill.
- **The frame** grows around what this batch has written. When the next
  target does not overlap it (the next slide, a part of the editor far away),
  the frame does not glide across the editor. It lands on the new target and
  fades in.
- Nothing is drawn until the cursor rests on something written
  (`data-placed`). Before that, the chat card's "being built" line is the
  only sign.

Arrow and tag look the same in both themes, so they read on any page. The
frame and the skeletons come from tokens in `src/index.css`:

| Token | Light | Dark | Used for |
|-------|-------|------|----------|
| `--presence-ink` | near-black | near-white | the frame |
| `--accent` | signal blue | signal blue | the arrow's glow and the landing ring (`--agent-glow` overrides it) |
| `--presence-frame-alpha` | 0.55 | 0.6 | the frame's strength |
| `--presence-pill-bg`, `--presence-pill-ink` | | | the slides editor's "working on slide N" chip |
| `--presence-skeleton`, `--presence-skeleton-sheen` | | | skeleton blocks and their shimmer |

When two or more agents build at once, `presenceTint` gives each one a muted
tint. It sets `--agent-glow` (the glow and the ring) and `--presence-ink` (the
frame). A single agent always glows in the signal colour. Use no other hue.

## Timings

`LIVE_TIMING` in `playback.ts`:

| Name | Value | Meaning |
|------|-------|---------|
| `fadeMs` | 220 | One unit fades from `fromOpacity` (0.3) to full. |
| `staggerMs` | 90 | From one unit's start to the next. |
| `maxBatchMs` | 3000 | A batch never plays longer. Long batches are compressed. |
| `maxUnits` | 60 | More units are revealed in groups. |
| `settleWaitMs` | 160 | The wait before a retry, and before opening mid-build. |
| `captureMs` | 700 | DOM changes this long after the batch started still join it (only with `lateJoin`). |
| `openSlideMs` | 150 | The node window sliding in. |

The presence, also in `playback.ts`:

| Name | Value | Meaning |
|------|-------|---------|
| `CARET_EASE_MS` | 35 | The cursor's ease-out time constant while it follows a caret. |
| `HOP_EASE_MS` | 110 | The same for a move from one written block to the next. |
| `THINKING_AFTER_MS` | 600 | Quiet after a batch before the tag shows the status. |
| `LEAN_MAX_DEG` | 10 | The most the arrow leans while it travels. |
| `RING_AFTER_PX` | 48 | A move at least this long opens a ring where the cursor lands. |

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

Do not ask the Dev assistant to build the node. Its chat may run on a local
model that cannot call tools: it answers that it has no tool for it. Play the
agent yourself instead: call the Dev app's own `node` tool over MCP, the way
a coding agent does.

1. Load the pull request in the Dev app: `python scripts/dev_preview.py <PR>`
   (docs/dev-preview.md). If another agent's preview is loaded and its pull
   request is still open, wait until it merges.
2. Find the endpoints. The Dev app uses every default port plus 100:
   - MCP tools: `http://127.0.0.1:47921/api/control/mcp/`
   - the lead chat's session id: `GET http://127.0.0.1:47921/api/agent-chat/lead`
     (`session_id` in the answer)
   - the window's DevTools port: first line of
     `<main checkout>/data-dev/webview/EBWebView/DevToolsActivePort`
3. Start a turn so the card shows "being built" and the window may open by
   itself: send the Dev lead chat any message that takes a while to answer
   (type it in the composer, or over DevTools: focus the composer's
   `[contenteditable="true"]`, then `Input.insertText` and an Enter key).
4. While that turn runs, call the `node` tool: one `create` with a skeleton
   spec, then several `update` calls with `changes`, a few seconds apart. The
   bearer is the control key; the `X-Jarvis-Chat-Session` header makes the
   write the lead's, in that chat. Run it with the main checkout's
   interpreter from the preview worktree (`.claude/worktrees/dev-preview`):

   ```python
   import asyncio
   from mcp import ClientSession
   from mcp.client.streamable_http import streamablehttp_client
   from dodaios.core.control_key import get_control_key

   URL = "http://127.0.0.1:47921/api/control/mcp/"
   SESSION = "<lead session id>"

   async def main():
       headers = {"Authorization": f"Bearer {get_control_key()}",
                  "X-Jarvis-Chat-Session": SESSION}
       async with streamablehttp_client(URL, headers=headers) as (read, write, _):
           async with ClientSession(read, write) as s:
               await s.initialize()
               made = await s.call_tool("node", {
                   "operation": "create", "type": "sheets", "title": "Monthly costs",
                   "spec": {"sheets": [{"name": "Costs", "columns": ["Item", "Amount"], "rows": []}]}})
               print(made.content[0].text)  # "... (node id <id>) ..."
               node = input("node id: ")
               for rows in (["Rent", 980], ["Power", 74]), (["Phone", 20], ["Gym", 30]):
                   await asyncio.sleep(5)
                   await s.call_tool("node", {"operation": "update", "node": node, "changes": [
                       {"op": "append", "path": "/sheets/0/rows", "value": r} for r in rows]})

   asyncio.run(main())
   ```

   Call `{"operation": "guide", "type": "<type>"}` first for the type's
   grammar. Each `update` is one batch the editor plays back.
5. Screenshot the Dev window over DevTools: take the page from
   `http://127.0.0.1:<port>/json` (the one on `127.0.0.1:47921`, without
   `solo=1`), then `Page.captureScreenshot` every half second while it
   builds. For the light theme, run
   `document.documentElement.classList.remove("dark")` in the page with
   `Runtime.evaluate`; add the class back for dark. Do not switch the theme
   in Settings: the setting is shared with the person's own app.
6. Check, in both themes: the window opened by itself, the skeleton showed,
   only the new content played in under the frame, tag and cursor, the view
   did not jump, and the composer kept its focus
   (`document.activeElement`).
7. Click into the content while a batch plays. It must finish at once, and
   the view must not scroll by itself after that. With reduced motion on in
   the OS, the content must appear at once, with the presence only.
8. Stop your Dev app afterwards, by its PID only (`dev_preview.py` prints it).
9. Unit tests: `npx vitest run src/components/nodes/live` and
   `pytest tests/unit/nodes/test_live.py`.
