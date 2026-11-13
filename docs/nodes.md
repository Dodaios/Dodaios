# Nodes

A node is something the assistant makes for a person and then looks after: a
document, a deck of slides, a sheet, a designed page, a dashboard, a
whiteboard, a short animation. The person sees it as a card in the Nodes
section of the app and as a card in the chat. The assistant can change it
later, take a change back, and keep it current from the person's apps.

## The seven types

| Type | Name in the app | What it holds |
|------|-----------------|---------------|
| `docs` | Docs | A written document: a report, a plan, a brief, notes. |
| `slides` | Slides | A deck of slides to present. |
| `sheets` | Sheets | Rows and columns: a list or a table to keep. |
| `design` | Visuals | A freely designed page: a poster, a one-pager, an invitation. |
| `data` | Analytics | A dashboard: current figures and charts. |
| `whiteboard` | Whiteboard | Notes, shapes and arrows: a diagram, a map of ideas. |
| `motion` | Clips | A short animation. |

The names in the app are the same in every language (`DISPLAY_NAMES` in
`dodaios/nodes/types.py`; a test keeps them equal to the app's strings). The
tool accepts them as type names too.

In the library a type's tile narrows the list to the nodes of that type; it
does not make a node. A new node starts from the "New" button, which opens on
the type the reader is looking at.

The list is `NODE_TYPES` in `dodaios/nodes/types.py`. The same file holds the
other names a person may use for a type (`deck`, `spreadsheet`, `dashboard`).

## Spec, renderer, revision, upkeep

**Spec.** The content of a node is its `spec`: plain JSON in the grammar of
its type. The assistant writes the spec. It never writes markup for a typed
node. A spec is at most one megabyte of JSON.

**Renderer.** Each type has one renderer in `dodaios/nodes/kinds/<type>.py`.
The renderer turns a spec into one self-contained HTML page. The same spec
always gives the same page. The page loads nothing from the network and works
in the light and in the dark theme. Because the renderer owns the layout,
every node of a type looks alike, and a better renderer improves every node.

A renderer module exports five names:

| Name | Purpose |
|------|---------|
| `normalize(spec)` | Checks and bounds the content. Returns a clean spec, or raises `NodeError` with one sentence that says what to send instead. |
| `render(node)` | Returns the page as one HTML document (`dodaios/nodes/shell.py` supplies the head, the theme and safe text helpers). |
| `preview(spec)` | Returns the few values the library draws on the node's card. |
| `starter(title, language)` | Returns the spec of a new, empty node of this type. |
| `GUIDE` | The grammar of the spec as text for the model, with one example. |

**Revision.** A change to a node is a change to its spec. The assistant sends
a complete new spec, or a list of small edits by path
(`dodaios/nodes/patch.py`):

| Edit | Effect |
|------|--------|
| `set` | Puts `value` at the path. On a list, the index after the last item or `-` appends. |
| `insert` | Puts `value` into a list before the index. `-` appends. |
| `remove` | Takes the key or the list item away. |
| `move` | Puts the list item at the path at index `to` of the same list. |
| `replace` | In the text at the path, puts `value` where `find` stands. `find` must occur exactly once (or pass `"all": true`). For an edit to a long text: a document's Markdown, a design's CSS. |
| `append` | Adds `value` to the end of the text at the path, or to the end of the list there. |

A path looks like `/slides/2/title`. After the edits the type's `normalize`
checks the result, so an edit cannot leave a spec the renderer does not
understand. Each revision adds one to the node's `version`. The store keeps
the last 12 earlier versions, so a change can be taken back (`revert`).

When a renderer's output changes, `RENDER_REVISION` in
`dodaios/nodes/kinds/__init__.py` goes up by one. The store then draws the
page of an older node again the next time it reads the node. The content and
the version stay the same.

**Upkeep.** Any node can be kept current. The node records what it tracks
(`track`) and how often to look (`every_minutes`, 15 minutes to one week,
default 180). The assistant then runs a routine on that schedule
(`dodaios/nodes/refresh.py`). The routine reads the sources and sends the
changed content through the `node` tool. A refresh changes content and never
the design. The routine is an ordinary routine of the assistant with the tag
`node:<node id>`. A person can stop it and start it again; the node keeps its
content.

## Where a node lives

A node is one run directory in the run archive
(`dodaios/nodes/store.py`):

```
<outputs root>/<time stamp>__node__<id>/
    .standalone-run.json                     marks the run (kind "node")
    node.json                                type, title, spec, version, upkeep
    history/v<N>.json                        earlier specs, the newest 12
    tasks/node/artifacts/files/<name>.html   the page, rendered from the spec
```

The id is twelve hex characters. Because a node is an ordinary run, the parts
of the app that know runs also know nodes: the stage that shows a page, the
Downloads mirror, the cleanup of old runs. The page is served by the outputs
route `/api/outputs/{slug}/files/{path}/page`, in a sandbox that allows
scripts and blocks the network.

The page file is always written again from the spec. Nothing edits it in
place. A rename keeps the file name, so links to the page stay valid.

## Comments on a node

On the stage, "Comment" switches a typed node's page into comment mode. A
click on the page then drops a numbered pin with a small field at that place.
The reader writes what should change and adds it with Enter or the tick. A
comment does not go out on its own: the reader can leave as many as they like,
and take one back with its cross. A "Send" button in the stage's toolbar
counts them ("Send 3 comments") and hands them all to the assistant at once.
Once they went out, each pin turns into a speech bubble with three moving
dots, and its note says the assistant is working the comment in. The bubbles
stay until the node's revision draws the page again.

The comments do not appear in the conversation. They go out as one request
(`POST /api/nodes/{id}/comments`, `dodaios/nodes/comments.py`) that runs as a
quiet one-shot lead routine, tagged `node-comments:<id>`: no start card, and
no result when every comment is worked in. Each comment carries the text the
pin was put on and the place in the node's own terms (`/slides/2`,
`Price × Netflix`, `§ Costs`). The assistant revises the node with the `node`
tool, and the stage draws the page again when the revision is written. Only a
run that fails, or a comment the assistant could not carry out, says so in the
conversation. The reader sent the comments with a click, so the run uses the
assistant's seat as it is, also when that seat bills an API key.

The page runs in a sandbox, so the app cannot see where the reader clicks in
it. The pin and its field are therefore drawn by the page itself
(`dodaios/nodes/bridge.py`, part of every node page), and the page and the app
talk in messages: the page says when it has loaded, adds a comment and takes
one back; the app says which mode it is in and where each comment stands
(waiting, sent, not sent) (`frontend/src/components/nodes/nodeBridge.ts`;
the waiting comments are kept in `nodeCommentDraft.ts`). While the mode is on, a click
does not reach the page's own controls. Pages that are not typed nodes (a
worker-built page, a report) take no comments.

A comment can also be spoken. The field has a microphone next to the tick.
The sandbox gives the page no microphone, so the page only asks the app
(`dodaios-node-dictate`), and the app records with the same dictation the chat
composer uses (`frontend/src/components/nodes/nodeCommentDictation.ts`). The
page is told whether it records or transcribes, and then gets the words as
plain text. They go after what the field already holds. Pressing the tick while
it records stops the recording, and the comment is added once the words are
in. While another dictation in the app has the microphone, the field's
microphone is disabled.

## Editing a node in its page

On the stage, "Edit" makes a typed node's page writable: the reader clicks a
text and types; leaving the field (or Enter) saves it, Esc puts the old text
back. Each change is one value of the spec, saved through
`POST /api/nodes/{id}/edit` (`dodaios/nodes/edit.py`): a JSON Pointer (or
`@title` for the node's name), what was typed, and what the field holds
(text, a number read in the reader's notation, or a yes/no). The type's
`normalize` judges the result as it does for the assistant's edits; a value
it refuses is a 400 with the reason, and the page puts the old text back.

A renderer decides what can be edited by marking it (see the docstring of
`dodaios/nodes/bridge.py`): `data-at` names the place, `data-src` holds the
stored value when the page shows something else (a document's body shows its
Markdown while it is edited), `data-as` says it is a number or a yes/no,
`data-multiline` lets Enter make a new line, and `data-refresh` asks for the
page to be drawn again after the save. A saved value is already on the page,
so the stage does not draw the page again for the reader's own revision; a
field that asks for it is drawn again at the same scroll position, and a
revision by the assistant still draws the page again.

## The `node` tool

The assistant works on nodes through one tool
(`dodaios/plugins/tool/node.py`):

| Operation | What it does |
|-----------|--------------|
| `guide` | Returns the grammar of a type. Without a type it lists the types. |
| `create` | Makes a node from `type`, `title` and `spec`. With `track` the node is kept current from the start. |
| `update` | Revises a node: a new `spec`, or `changes`, and/or a new `title`. On a refresh run, `note` records why no source could be read. |
| `get` | Returns a node with its spec. |
| `list` | Returns all nodes. |
| `revert` | Puts the previous version back. |
| `keep_current` | Starts or changes the upkeep (`track`, `every_minutes`). |
| `stop` | Stops the upkeep. |

A node is named by its id or by its exact title.

## The library

The Nodes section shows one list of cards. It holds the typed nodes and
everything older runs left behind. `dodaios/nodes/library.py` builds the list:

| Source | Card type | `origin` |
|--------|-----------|----------|
| A typed node | Its own type | `node` |
| A living page (`__living-page__` run) | `sheets` | `living` |
| A report page (`__report__` run) | `docs` | `report` |
| Any other HTML page a run wrote | `design` | `page` |
| A picture or an SVG | `design` | `file` |
| A PDF | `docs` | `file` |
| A running run that still builds its page | `design` | `build` |
| A run that left no page, picture or PDF | `output` | `run` |

Only a card with the origin `node` has a spec and can be renamed, copied or
reverted. The other cards are files; they are opened, and deleted through
`/api/outputs`.

The list comes from the two listings the outputs routes already serve: the
run list and the file listing of a run. So the library shows a file only if
it is a deliverable of its run. The files of the newest 60 runs are read
(`?scan=` changes this). An older run still has a card; its files are read
when the card is opened. Cards for work in progress come first, then the
cards are in the order of their last change.

A page takes its title from its own `<title>`. A run card shows the summary
of the run, or the first lines of the answer the run wrote down. The card
shape is `NodeCard` in
`dodaios/ui/web/frontend/src/components/nodes/nodeModel.ts`.

## HTTP API

All routes are in `dodaios/ui/web/nodes_routes.py`.

| Route | Result |
|-------|--------|
| `GET /api/nodes` | The library: `{"nodes": [card, ...], "scanned_runs", "skipped_runs"}`. `?scan=<n>` sets how many runs are read (1 to 500, default 60). |
| `GET /api/nodes/types` | `{"types": [{"type", "guide"}, ...]}`. |
| `GET /api/nodes/{id}` | One typed node with its spec (`?spec=0` leaves the spec out). |
| `GET /api/nodes/by-slug/{slug}` | The typed node of a run directory, with its spec (`?spec=0` leaves it out; the stage asks this way every few seconds to see a revision). |
| `POST /api/nodes` | Body `{"type", "title"?, "language"?}`. Makes a node from the type's starter and returns its card. |
| `PATCH /api/nodes/{id}` | Body `{"title"}`. Renames the node and returns its card. |
| `POST /api/nodes/{id}/duplicate` | Body `{"title"?}`. Makes a second node with the same content and returns its card. The copy has no upkeep and no history. |
| `POST /api/nodes/{id}/edit` | Body `{"path", "value", "as"}`. Saves one value the reader typed into the page; answers with the node's state. |
| `POST /api/nodes/{id}/revert` | Puts the previous version back and returns the card. |
| `POST /api/nodes/{id}/upkeep/stop` | Stops the upkeep and returns the node. |
| `POST /api/nodes/{id}/upkeep/resume` | Body `{"every_minutes"?}`. Starts the upkeep again and returns the node. |
| `DELETE /api/nodes/{id}` | Stops the upkeep, then removes the node, its page and its history. Returns `{"deleted": true}`. |

Errors: `404` for an id that is not a node. `400` with the reason as one
sentence for a request the store refuses (an unknown type, an empty title, no
earlier version, no `track` to resume). `422` for a body of the wrong shape.
`503` when the upkeep cannot be scheduled because the task scheduler is not
running.

The content of a node is not written through these routes. The assistant
writes it through the `node` tool.

For a typed node, `refreshing` is checked against the routine in every
answer. If a person deleted or paused the routine in Automations, the node
reads as not refreshing. For a living page the library reports what the page
last recorded.

## Add a type

1. Add the name to `NODE_TYPES` in `dodaios/nodes/types.py` and to
   `NODE_TYPES` in `nodeModel.ts`. Add the other names people use to
   `_ALIASES`.
2. Write `dodaios/nodes/kinds/<type>.py` with `normalize`, `render`,
   `preview`, `starter` and `GUIDE`. Send every text from the spec through
   the helpers in `dodaios/nodes/shell.py`; they escape. Build the page with
   `shell.document`.
3. Add the preview shape of the type to `nodeModel.ts` and a cover for the
   card in `frontend/src/components/nodes/`.
4. Add one line for the type to `TYPE_LINES` and to the description of the
   tool in `dodaios/plugins/tool/node.py`.
5. Add the default title of a new node to `DEFAULT_TITLES` in
   `dodaios/ui/web/nodes_routes.py`.
6. Add tests for the renderer in `tests/unit/nodes/`.

When you change what an existing renderer writes, raise `RENDER_REVISION` by
one.

## Code

| Part | File |
|------|------|
| Types, the error class | `dodaios/nodes/types.py` |
| One node, its fields | `dodaios/nodes/model.py` |
| Reading and writing nodes | `dodaios/nodes/store.py` |
| Edits by path | `dodaios/nodes/patch.py` |
| The document around a page, safe text | `dodaios/nodes/shell.py` |
| Renderers | `dodaios/nodes/kinds/` |
| Upkeep | `dodaios/nodes/refresh.py` |
| The library's cards | `dodaios/nodes/library.py` |
| The tool | `dodaios/plugins/tool/node.py` |
| HTTP API | `dodaios/ui/web/nodes_routes.py` |
| Card model of the frontend | `dodaios/ui/web/frontend/src/components/nodes/nodeModel.ts` |
