# Nodes

A node is something the assistant makes for a person and then looks after: a
document, a deck of slides, a sheet, a dashboard, a
whiteboard, a short animation. The person sees it as a card in the Nodes
section of the app and as a card in the chat. The assistant can change it
later, take a change back, and keep it current from the person's apps.

## The six types

| Type | Name in the app | What it holds |
|------|-----------------|---------------|
| `docs` | Docs | A written document: a report, a plan, a brief, notes. |
| `slides` | Slides | A deck of slides to present. |
| `sheets` | Sheets | Rows and columns: a list or a table to keep. |
| `data` | Analytics | A dashboard: current figures and charts. |
| `whiteboard` | Whiteboard | An infinite canvas: shapes, notes, arrows, drawings, pictures, a diagram. |
| `motion` | Clips | A short animation. |

The names in the app are the same in every language (`DISPLAY_NAMES` in
`dodaios/nodes/types.py`; a test keeps them equal to the app's strings). The
tool accepts them as type names too.

In the library a type's tile narrows the list to the nodes of that type; it
does not make a node. A new node starts from the "New" button, which opens on
the type the reader is looking at. A new node is empty, like a new file in an
office app: no sample text and no sample figures, only the editor's greyed
hints where content goes (each type's `starter`). Whatever the person empties
in an editor saves.

The list is `NODE_TYPES` in `dodaios/nodes/types.py`. The same file holds the
other names a person may use for a type (`deck`, `spreadsheet`, `dashboard`).

## Spec, renderer, revision, upkeep

**Spec.** The content of a node is its `spec`: plain JSON in the grammar of
its type. The assistant writes the spec. It never writes markup for a typed
node. A spec is at most one megabyte of JSON (a whiteboard's eight, see
[Whiteboards](#whiteboards)).

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

A renderer may also export `render_in_run(node, run_dir)`: the page drawn with
files the node keeps in its run directory (a whiteboard's pictures). The store
uses it when it is there.

**Revision.** A change to a node is a change to its spec. The assistant sends
a complete new spec, or a list of small edits by path
(`dodaios/nodes/patch.py`):

| Edit | Effect |
|------|--------|
| `set` | Puts `value` at the path. On a list, the index after the last item or `-` appends. |
| `insert` | Puts `value` into a list before the index. `-` appends. |
| `remove` | Takes the key or the list item away. |
| `move` | Puts the list item at the path at index `to` of the same list. |
| `replace` | In the text at the path, puts `value` where `find` stands. `find` must occur exactly once (or pass `"all": true`). For an edit to a long text: a document's Markdown. |
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
    board-files/<hash>                       a whiteboard's pictures
    tasks/node/artifacts/files/<name>.html   the page, rendered from the spec
```

The id is twelve hex characters. Because a node is an ordinary run, the parts
of the app that know runs also know nodes: the stage that shows a page, the
Downloads mirror, the cleanup of old runs. The page is served by the outputs
route `/api/outputs/{slug}/files/{path}/page`, in a sandbox that allows
scripts and blocks the network.

The page file is always written again from the spec. Nothing edits it in
place. A rename keeps the file name, so links to the page stay valid.

## Whiteboards

A whiteboard is an infinite canvas. The person draws on it in the app: the
stage shows the embedded open-source editor `@excalidraw/excalidraw` (MIT
licence) instead of the page. The assistant draws on the same board with the
`whiteboard` tool, whose actions are high level: a box with a label, an
arrow between two things, a frame, a whole diagram, a Mermaid flowchart, a
layout. Several boards are several nodes; "New whiteboard" makes another.

**The canvas.** The editor is the engine; its own toolbars are hidden and the
board draws its own controls in the app's look
(`dodaios/ui/web/frontend/src/components/nodes/whiteboard/canvas/`): a tool
dock at the bottom (tool lock, select, move, frame, shapes, arrow, line,
pen, text, sticky note, picture, eraser, laser pointer; N adds a sticky
note; under "more": lasso select (W), paint bucket (B), draw to shape
(Shift+X), Mermaid, library), an inspector on the
right for the selection (colour, fill, stroke, corners, clean or sketched
lines, font, size, alignment, opacity, layers, duplicate, lock, delete), a
menu (export, save and open a file, find, grid, shortcuts, background,
clear), undo and redo, and the zoom. What the person draws is clean by
default: no sketched lines, the normal font, round corners. The ground is
the app's dotted stage; a board with a background colour of its own shows
that colour instead. The view glides: a mouse wheel notch or a zoom button
moves it over a few frames, a trackpad's own stream is followed at once,
and Ctrl or Cmd with the wheel zooms around the pointer.

The editor package does not ship a lasso, a paint bucket or draw to shape,
so the board has its own (`canvas/boardTools.ts`, `canvas/ToolOverlay.tsx`):
the lasso selects what its loop fully encloses (a group whole, Shift adds),
the bucket fills the topmost closed shape under the click with the colour
the inspector shows, and in draw to shape a finished pen stroke that reads
as a rectangle, an ellipse or a diamond becomes that shape, a straight one
an arrow (a scribble stays a drawing; one step to undo). The laser pointer's
trail and pointer are the brand's gold. Left out on purpose: the web embed
(the board loads nothing from the web) and the editor's AI tools (the
assistant draws instead).

**Watching the assistant draw.** The open board asks every one and a half
seconds whether the node changed. When the assistant drew something, its
new pieces land one at a time (frames first, then each box with its label,
then the arrows, in under three seconds) while the assistant's cursor, with
its name, moves to each piece. A board opened within a minute and a half of
the assistant's drawing plays that drawing the same way. The tool marks what
it draws with `customData: {"by": "assistant"}`.

**The spec is the editor's scene** (`dodaios/nodes/board/scene.py`):

```json
{
  "format": "scene",
  "elements": [{"id": "a1", "type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 100, "version": 1, "...": "..."}],
  "appState": {"viewBackgroundColor": "#ffffff", "gridModeEnabled": false},
  "files": {"<fileId>": {"id": "<fileId>", "mimeType": "image/png", "created": 1731500000000}}
}
```

The element types are `rectangle`, `ellipse`, `diamond`, `text`, `arrow`,
`line`, `freedraw`, `image` and `frame`, with the editor's own fields.
`normalize_scene` keeps only these types and fields, bounds every number and
string, accepts a colour as hex, `transparent` or a short list of words, and
keeps links to `https:`, `http:` and `mailto:` only. Unknown fields are
dropped; an unknown element type is refused with a sentence that names the
element. The editor's `embeddable`, `iframe` and generated-page frames are
dropped, because they load the web. A board holds at most 5 000 elements,
and its spec may be eight megabytes, because a drawn stroke has many points.

**Versions and the merge.** Whoever changes an element raises its `version`
and draws a new random `versionNonce`. A deleted element stays in the list
with `isDeleted: true` (a tombstone). When the editor saves, the store joins
its scene with the stored one (`merge_scene`): per element the higher version
wins, and on a tie the lower nonce, as in the editor. An element only the
stored scene has stays, so what the assistant drew meanwhile is kept. When
the stored scene had something newer, the answer carries the merged scene and
the editor takes it. Old tombstones are pruned when there are more than 2 000.

**History.** The editor saves about once a second while the person draws.
Saves less than ten minutes apart share one history version, for at most an
hour; the version number still goes up with each save. Any other revision
(the assistant's, a revert) ends that stretch. Changes to one node are
serialised by a lock, so a save and an edit by the assistant cannot overwrite
each other.

**Pictures.** The scene keeps only a picture's metadata. The bytes are in the
node's run directory, under `board-files/`, in a file named by a hash of the
file id. A picture is kept only when its bytes are a PNG, JPEG, GIF or WebP
(whatever the upload claims), at most 5 MB each and 50 MB per board. When a
board passes its budget, pictures that neither the scene nor a kept version
names are removed first. A duplicated board gets a copy of its pictures.

**The page** (`dodaios/nodes/board/render.py`) is a read-only drawing of the
scene as SVG, for the library card, the chat card and a shared file. It
draws clean lines even where an element asks for the hand-drawn look, fits the drawing
into the window, and pans and zooms. In the dark theme the drawing is
inverted as the editor does it, and pictures are inverted back. Pictures are
embedded up to 3 MB per page; the rest are labelled boxes.

**The older grammar.** Boards made before the canvas used `items`, `links`
and `layout`. The `node` tool still accepts that grammar; it becomes a scene
laid out by the auto layout (`dodaios/nodes/board/convert.py`). A stored board
in the older grammar is converted the next time it is read, and its embedded
pictures become board files.

## Clips

A clip (`motion`) is a short film of scenes on one timeline. The spec holds
only the scenes: their type (`title`, `text`, `bullets`, `stat`, `bars`,
`chart`, `steps`, `quote`, `image`, `end`), their words and numbers, their
length in seconds (1.5 to 20) and the transition they come in with (`fade`,
`slide`, `zoom`, `cut`). The whole clip has a format (`wide`, `square`,
`tall`), a dark or light background, one accent colour and a loop switch.
How the scenes move is decided by the renderer
(`dodaios/nodes/kinds/motion.py`), so every clip has the same calm motion.

**Chart scenes.** A `chart` scene holds the shared chart grammar
(`report_blocks.parse_chart`, the same JSON as a report's `chart` block) and
draws the kit's chart card, revealed from left to right (a pie or donut
fades in). The renderer keeps the chart in the parser's own reading, so a
spec read twice is the same spec. A chart with one series wears the clip's
accent.

**The clip editor.** "Edit" on a clip opens the native editor
(`frontend/src/components/nodes/editors/motion/`):

* The preview is the real film, drawn by the server from the unsaved spec
  (`POST /api/nodes/{id}/preview`). It stands on the picked scene, settled,
  and its texts can be clicked and typed into right there (the bridge's edit
  mode; each edit is applied to the spec as one undo step). "Play" (or Space
  on a scene) plays from the picked scene; when the film ends or is paused,
  the editor stands on the scene it reached. A new page loads in a second,
  hidden frame and takes over once it is ready, so a change never blanks the
  preview.
* The timeline shows every scene as a block as long as it runs, and the
  total length. A block is dragged sideways to reorder (or moved with
  Alt+arrow); its right edge drags its length (or takes the arrow keys, a
  tenth of a second, half a second with Shift). Between two blocks the
  transition of the later scene can be changed. Delete removes a scene,
  Cmd/Ctrl+D duplicates it, "+" adds a scene of a type after the picked one.
* The inspector holds the picked scene's type (a switch keeps the words that
  carry over), every field that type keeps, capped at the length the server
  keeps, the lists (points, bars, steps) with add, move and remove, the
  picture (made small enough to embed: at most 1600 px and 400,000
  characters), the chart (the shared chart editor), the length with "Fit to
  content" (the renderer's default length for that content) and the
  transition.
* The toolbar holds the whole clip's format, background, accent (the kit's
  six colours are kept by name, so the film takes that colour's shade for
  its theme) and loop.

Every change is an undo step of the shared editor history and saves itself.
A scene may be blank: a new clip is one title card with no text, and a scene
whose words are all deleted saves as it is (a blank card plays as an empty
frame). A save waits only while a chart scene's chart cannot be drawn, and
the save state says which scene and what.

The editor steers the page in two messages of the film's own, accepted only
from the parent frame: `dodaios-film-seek` `{t, play}` moves the clock (and
plays), and the page answers with `dodaios-film-time`
`{t, scene, playing, total}` on every change of scene or play state and a
few times a second while it plays. `data-film-scene` on `<html>` opens a
page standing on a scene instead of playing from the start.

## Sheets

A sheet node (`sheets`) is a spreadsheet of 1 to 12 sheets
(`dodaios/nodes/kinds/sheets.py`). Each sheet has typed columns (text,
number, currency, percent, date, yes/no, status, link) with a unit, decimals,
a total (sum, average, minimum, maximum, count) and an optional formula. It
also has up to 1,000 rows, up to 3 frozen leading columns and up to 8 charts.
The page writes numbers and dates in the reader's locale, and the reader
sorts, filters and moves through the grid.

* **Formulas are column formulas.** A formula is arithmetic over the row's
  other columns by key (`qty * price`, `round(a / b * 100, 1)`). Python
  computes it with a small, checked grammar and never `eval`. There are no
  per-cell formulas such as `=B2*C2`. A cell is found by its row's place,
  and a sort or an inserted row changes that place, so a cell reference would
  quietly point at another value. A column formula and a total depend on the
  row and the column only, and reordering rows cannot break them.
* **A column's look** is stored on the column: `width` (48 to 480 px),
  `align`, `bold` and a named `color` (the theme's tokens, never a colour
  value). Cells stay plain values, so formulas, totals, sorting and the
  assistant read them without unwrapping them.
* **Charts** are stored in the shared chart grammar under the sheet's grid.
  A chart can be literal (labels and numbers, like a report's chart) or
  bound to the sheet: `x` names the label column, each series names a
  `column`, and `rows` is an optional 1-based range. A bound chart reads its
  numbers each time the page is drawn, so it follows the cells. A bound chart
  that cannot be drawn right now (one row left) shows an empty card. It does
  not make the save fail.
* **Blank rows** between filled rows are kept (the editor inserts them to
  fill in later). Blank rows at the end are dropped.

**The Sheets editor** (`frontend/src/components/nodes/editors/sheets/`) is a
spreadsheet grid. It is keyboard-first:

* Arrows move the selection; Shift extends it. Cmd/Ctrl+arrow jumps to the
  edge of the filled block. Home and End go to the start and end of the row,
  and with Cmd/Ctrl to the start and end of the data. Page Up and Page Down
  move by a screen. Cmd/Ctrl+A selects everything, Shift+Space selects the
  row, and Ctrl+Space selects the column. A click selects, a drag or a
  Shift+click extends, and a click on a row number or a column head selects
  the row or the column.
* Typing replaces the cell. F2, a double-click or the formula bar edits the
  value as it is. Enter, Tab, Shift+Enter and Shift+Tab commit and move. In
  a selected range they move inside the range. Escape cancels. Delete
  empties the selection. Space toggles a yes/no cell. Input methods work,
  because typing goes into a real text field over the active cell.
* Copy, cut and paste carry tab-separated text, the format other
  spreadsheet apps read and write (quoted cells with tabs, line breaks and
  quotes too). Pasted text is read per column type: numbers in the person's
  notation, with currency signs and grouping; dates in ISO form or the
  locale's order; yes/no words. A paste wider than the sheet adds columns,
  and a paste below the data adds rows. A single value pasted into a range
  fills the range.
* Cmd/Ctrl+D fills down and Cmd/Ctrl+R fills right. Rows and columns are
  inserted above, below, left or right, and deleted, from the context menu
  (right click, the menu key or Shift+F10) or the Insert menu. A column that
  a formula reads cannot be deleted; the editor names the formula column.
  Columns move left and right from the column head's menu. A column is
  resized by dragging its head's edge.
* The toolbar sets the selected columns' type and number format, decimals,
  and bold; it sorts by the active column (the stored rows are reordered) and
  filters. A filter is a column's value list and only hides rows while the
  person works; it is not saved. The page has its own filter for readers.
  "Column settings" opens the inspector: name, type, unit or currency code,
  decimals, total, formula (checked as it is typed, with the other columns'
  keys listed), width, alignment, bold, colour, and the sheet's frozen
  columns and note.
* The header row and the frozen columns stay in view. The totals row stays
  at the bottom. Below the data, empty rows are offered to type into. The
  grid draws only the rows in view, so 1,000 rows scroll smoothly.
* "Insert chart" opens the shared chart editor on the selection (all
  columns when one cell is selected; all rows when one row or less is
  selected). The chart is stored bound to the chosen columns and rows,
  clipped to what the chart type can draw. Charts appear under the grid and
  can be edited or deleted there.
* The sheet tabs add, rename (double-click or F2), reorder (drag, or
  Alt+Shift+arrow) and, from a tab's menu, duplicate and delete sheets. The
  last sheet stays.

Every grid action is one undo step with its name ("Paste", "Sort by
Amount"). A typed cell is one step when it is committed. Cmd/Ctrl+Z works
from the grid; while a cell is being typed in, it undoes the typing. A save
waits, with the reason, while a formula is one the server would refuse.

## Documents

A document (`docs`) is a summary line and a body of Markdown
(`dodaios/nodes/kinds/docs.py`). The page draws the body with the report
pipeline (Python-Markdown with the "extra", "sane_lists" and "toc"
extensions, raw HTML shown as text) and the report blocks
(`report_blocks.py`): a fenced `chart` block, a fenced `metrics` block, a
quote opening with `[!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]` or
`[!CAUTION]` (a callout), a numbered list of bold-titled items (steps), and
a list of links (sources). On top of that the docs page draws `~~struck~~`
text and checklist items (`- [ ]`, `- [x]`) as a box that cannot be
changed on the page. A picture is shown only when it is embedded (a data URI); one from
an address is its description.

**The document editor.** "Edit" on a document opens a rich-text editor
(`frontend/src/components/nodes/editors/docs/`, TipTap on ProseMirror):

* The page's title, then the summary as the first line (plain text, Enter
  goes on into the body), then the body as it reads: headings, paragraphs,
  bold, italic, strikethrough, inline code, links, bulleted, numbered and
  check lists (nested with Tab), quotes, callouts in their five tones, code
  blocks, tables, dividers, pictures, charts and key figures.
* The toolbar holds the block type (text, section heading `##`, subheading
  `###`, minor heading `####`), the marks, the link form (Cmd/Ctrl+K),
  the lists, quote, callout and code block, and "Insert" (table, chart, key
  figures, picture, divider). While the caret is in a table, the toolbar also
  holds rows and columns (insert above, below, left, right; delete) and the
  column's alignment, which Markdown keeps per column. The outline button
  opens the headings in the side panel; a click goes to the heading.
* Markdown typed at the start of a line becomes its block (`## `, `- `,
  `1. `, `[ ] `, `> `, three backticks, `---`, `[!tip] ` for a callout),
  and `**bold**`, `*italic*`, `~~struck~~` and backticks become marks.
  The keys, each with Cmd/Ctrl: B, I, E (code), Shift+S (strike),
  Shift+7/8/9 (numbered, bulleted, check list), Shift+B (quote), Alt+C
  (code block), Alt+1/2/3 (the three headings), Alt+0 (text), K (link).
* A chart block is drawn as the chart (`charts/ChartPreview.tsx`) and edited
  in the shared chart dialog. A chart whose JSON the grammar cannot draw is
  offered as its JSON to fix. Key figures are edited as up to six value,
  label and detail fields.
* A picture is pasted, dropped or picked, then scaled down and embedded as a
  JPEG data URI until it fits in what is left of the body's 200,000
  characters. A picture that cannot fit is refused with a sentence.
* Undo and redo are the text editor's own history for the whole document,
  summary included. The frame's buttons and keys use it. Saving, conflicts
  and the assistant's revisions are the shared `useNodeSpecEditor`. A
  revision taken while open replaces the content, and one undo brings the
  person's version back. A save waits with a sentence when the body is
  longer than the server keeps. An empty body saves: a new document starts
  empty, with the caret on its first line and greyed hints for the summary
  and the text.

**How the Markdown survives.** The editor reads the body with markdown-it
(`markdown/parse.ts`) and writes it back with its own writer
(`markdown/serialize.ts`) in the subset that Python-Markdown and markdown-it
read the same way:

* list items are nested by four spaces;
* blocks are separated by a blank line;
* a hard break is two trailing spaces;
* only characters Python-Markdown can unescape get a backslash, and the rest
  are written as character references (`&#126;` for a literal `~~`).

Python-Markdown merges a quote with a quote above it, and a list with a list
of its kind above it, even across a blank line. The writer keeps them apart
with a paragraph holding only `&#8203;`, which draws nothing and which the
reader drops again.

A block the person did not touch keeps its exact original text, and so does
the gap between two untouched neighbours (`markdown/document.ts`). Blocks
are matched by their content, not their position. Opening and closing a
document therefore changes nothing, and an edit rewrites only the blocks it
touched. Shapes only Python-Markdown knows (a footnote, abbreviation or
definition-list paragraph, a lone attribute list) are kept as a "Markdown"
block that is edited as text. Link reference definitions are kept while a
block still uses them.

Limits of the writer, in edited blocks only:

* Markdown has no underline, so the editor offers none.
* Bold or italic on inline code is dropped, because the code mark excludes
  other marks.
* A link's title is kept, but it cannot be edited.
* A list written loose (blank lines between items) is written tight when it
  is edited.
* A paragraph's line breaks inside a sentence become spaces.

The round trip is tested both ways on shared fixtures (`docs/__fixtures__/`):
the frontend tests that each fixture keeps its text untouched and means the
same when it is written again. `tests/unit/nodes/test_kind_docs.py` tests
that the page drawn from the editor's text holds every block of the original.

## Analytics

An analysis (`data`) is a dashboard: a summary, the named `sources`, and up
to 12 sections, each with a title, a short text, metric tiles (label,
value, change, detail, and `better: lower` for a figure whose fall is good
news), charts in the shared chart grammar, and tables
(`dodaios/nodes/kinds/data.py`). Charts keep the grammar's `stacked` and
`colors` when they say something, and a pie or donut is drawn at its own
size beside its legend instead of on the plot frame the other kinds scroll
on. A dashboard can be kept current: the new-node dialog asks where the data
comes from and how often to look, and the refresh reads those sources again.

**The Analytics editor** (`frontend/src/components/nodes/editors/data/`)
lays the dashboard out as the page does: tiles in rows of even length,
charts two per row with wide ones across, tables below, every text typed
where it stands.

* Every tile, chart, table and section can be selected, moved earlier or
  later (its buttons, the arrow keys on its handle, or a drag in its row),
  duplicated (Cmd/Ctrl+D) and deleted (Delete). "Metric", "Chart", "Table"
  and "Section" add one to the selected section, up to the limits the
  renderer keeps (8 tiles, 8 charts, 4 tables, 12 sections).
* Charts are made and changed in the shared chart editor; the width in the
  row ("Full width") is the dashboard's and stays when a chart is edited.
* A table is a small grid: Enter and the arrows move between cells, Enter on
  the last row adds one, rows and columns are added and removed, and cells
  pasted from a spreadsheet or a CSV file fill it from the cell they land in,
  growing it. A plain number is saved as a number; text with a unit or a
  currency stays text, which the page still reads as a number.
* The inspector holds what has no place on the page: "Lower is better",
  "Full width", moving a piece to another section, and with nothing selected
  the summary and the sources.
* "See the page" shows the real page drawn from the unsaved spec.

Every part can be deleted, the last one too: an empty dashboard saves (a new
one starts empty), and deleting the only section empties it instead, so
there is always a place to add to. A save waits, with the reason, while a tile lacks its label or
value or a table its column names. The status of a kept-current dashboard
is the stage's upkeep bar above the editor; the inspector adds that a
refresh may replace values typed by hand and keeps the layout.

## Decks

A deck (`slides`) is a list of slides, each a layout and that layout's
fields (`dodaios/nodes/kinds/slides.py`, the grammar is in its `GUIDE`): an
opening (`title`), a chapter divider (`section`), points (`bullets`),
`columns`, a `quote`, figures (`stats`), a `chart`, a `table`, a picture
(`image`), numbered `steps`, a `closing` slide and an empty canvas
(`blank`). Every slide may carry speaker notes. The page is a 16:9 player
with an overview, the notes, transitions and animations.

Two things the layouts hold besides their texts:

* A chart slide's `chart` is the shared chart grammar, so it may be a pie or
  a donut, stack its columns or bars (`"stacked": true`) and name its
  colours (`"colors"`); a bar chart shows its first 10 rows.
* An image slide's `fit` is `"contain"` to show the whole picture (a
  screenshot, a diagram) instead of cropping it to its box.

A slide that names its layout but lacks the layout's main field still takes
the layout its fields fit (a `chart` slide without a chart becomes a
section). A layout that can be drawn blank (`title`, `section`, `bullets`,
`quote`, `stats`, `steps`, `closing`, `blank`) keeps its place and layout
even when every text was deleted: a new deck is one blank title slide, and
an emptied deck saves. An emptied column or table grid keeps its place too.
A slide of only elements or only a background is a `blank` one.

**Free elements and the look** (`dodaios/nodes/kinds/slide_elements.py`).
On top of its layout every slide may carry up to 40 `elements`, placed on
the slide's logical 1280 x 720 px canvas and drawn in order (the last on
top):

| Element | What it holds |
|---------|---------------|
| `text` | A text box: lines with inline marks, size, one of 18 font families, colour, bold, italic, underline, strike, capitals, alignment, vertical position, a bulleted or numbered list (a line per item), line height, letter spacing, fill, outline, corners, inner margin. |
| `shape` | A rectangle, rounded rectangle, ellipse, triangle, diamond, pentagon, hexagon, star, block arrow, chevron, parallelogram, trapezoid, speech bubble or plus, with fill and outline, and a centred text with the text box's settings. |
| `line` | A line from `x1, y1` to `x2, y2`: colour, width, dashes, an arrow head or a dot at either end. |
| `image` | A picture in a box: cropped, shown whole or stretched, with corners and an outline. |
| `table` | Rows of short cells, the first the header unless `"head": false`, with size, font and colours. |
| `chart` | A chart in the shared chart grammar, in a box. |

Every element may be rotated, made transparent, cast a shadow, carry a link,
be locked in place, and come in with an animation (`fade`, `rise`, `slide`,
`zoom`, `pop`, `wipe`): with its slide, one after the other, or one per
click (`"click": true`). A colour is a hex, rgb()/hsl(), one of the kit's
names, `accent` (the deck's accent), `white`, `black` or `transparent`. A
font is a class from a fixed list, never a free style.

A slide may also have a `background` (a colour, a gradient, or a picture
with a dark veil, `dim`), a `tone` (its text drawn light or dark whatever
the deck's theme is; a dark background picks the light tone by itself), a
`transition` (`none`, `fade`, `slide`, `rise`, `zoom`), `hidden: true`
(skipped when presenting, dimmed in the overview) and `footer: false`. The
deck carries the defaults: `background`, `transition`, a type pairing
(`font`: `sans`, `serif`, `editorial` with serif titles, `mono`, `rounded`,
`condensed`, `geometric`, `classic`) and `footer: false` for no footers.

A deck holds its pictures inside its spec, so its spec may be 3.6 MB
(`SLIDES_SPEC_BYTES`, about nine full pictures) instead of one.

**The deck editor.** "Edit" on a deck opens the native editor
(`frontend/src/components/nodes/editors/slides/`), built like a presentation
program:

* The toolbar adds, duplicates and deletes slides; inserts a text box, a
  shape (14 kinds), a line or an arrow, a picture, a table or a chart;
  opens "Design" (nine ready-made looks that set theme, accent, type and
  background at once, and each of them alone, with the transition every
  slide takes and the footers); sets the theme and the accent; shows a grid
  and switches snapping; and presents (from this slide, from the start, or
  in the presenter view).
* The strip shows every slide as a live thumbnail. "New slide" adds a slide
  of a picked layout after the selected one, filled with short sample texts
  in the person's language. A thumbnail is dragged to a new place; the strip
  is a listbox (arrows select, Alt+arrow moves, Cmd/Ctrl+D duplicates,
  Delete removes, Enter goes to the title). Each thumbnail has a menu,
  including "Hide slide"; a hidden slide is dimmed and marked.
* The selected slide stands large in the middle. Every text of its layout is
  typed into directly. A click selects an element (Shift or Cmd/Ctrl adds),
  a drag moves it, snapping to the slide's edges and middle and to the other
  elements with guides (Alt moves freely, Shift keeps one axis); eight
  handles resize it (Shift keeps the proportions, a rotated element resizes
  along its own axes), the round handle rotates it (Shift: 15° steps), and a
  line has a handle at each end. A drag on the empty slide selects with a
  frame. A double click writes into a text box, a shape or a table, opens a
  chart's editor, or replaces a picture; Cmd/Ctrl+B and +I wrap the selected
  words in bold or italic marks. A text box left empty goes.
* The keys on the slide: arrows nudge (Shift: 10 px), Delete removes,
  Cmd/Ctrl+C, X and V copy, cut and paste (also into another slide),
  Cmd/Ctrl+D duplicates, Cmd/Ctrl+A selects all, Cmd/Ctrl+] and [ move
  forward and back (with Shift: to the front, to the back), Enter writes,
  Escape lets go. A right click opens the same actions. A picture pasted or
  dropped onto the slide becomes a picture element where it was dropped;
  pasted text becomes a text box.
* The format bar above the slide holds what is used most: for text, font,
  size, bold, italic, underline, colour, alignment and lists, and the fill;
  for a line its colour; with nothing selected, the slide's layout,
  background, transition and whether it is hidden.
* The inspector holds the rest. With elements selected: position, size and
  rotation in numbers; every text setting; the shape's kind; fill, outline,
  dashes, corners, shadow and opacity; the picture's fit and description;
  the line's ends; the table's cells, rows, columns and colours; the chart's
  editor; the animation and when it starts; the link; and arranging (order,
  align to the slide or to each other, spread three or more evenly). With
  nothing selected: every field of the slide's layout (the lists with add,
  move and remove, the picture, the chart), then its background (with "Use
  for every slide"), text colours, transition, hidden and footer. Changing
  the layout carries the content over, and the elements, background and
  settings stay.
* "Present" plays the unsaved deck full screen: transitions, animations one
  click at a time, hidden slides skipped. N shows the notes, P the presenter
  view (this slide, the next, the notes, a timer and the clock), B and W
  blank the screen, Escape ends on the slide reached.

Every action is one step of the editor's undo history (typing in one field
is one step per run, a drag is one step); undo and redo select the slide
they change.

How the editor draws a slide: in React (`SlideView.tsx`, `elements.tsx`),
with the same elements and classes as `slides.py` and `slide_elements.py`,
inside a shadow root that carries the page's own stylesheet, taken once from
`POST /api/nodes/{id}/preview` (the theme tokens move from `:root` to
`:host`). The canvas, the thumbnails and the presenter are therefore the
page's exact look without a request per keystroke. The charts' figures are
the one exception: drawn by the server's chart renderer, fetched from the
preview route when a chart changes. `tests/unit/nodes/test_kind_slides.py`
writes the page's markup of one slide of every shape, elements and
backgrounds included, to `slides/__fixtures__/slides_markup.json` (and
fails when it is stale); `SlideView.test.tsx` checks the editor draws the
same tree.

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

## Editing a node

"Edit" on the stage opens the node's native editor, one per type, in the
app (`frontend/src/components/nodes/editors/`; a whiteboard has its own
canvas, see Whiteboards). The editor works on the spec, not on the page: the
page stays the reading view, the cover and what is shared, and Done draws it
again from the saved spec. A node started blank from the library opens
straight in its editor. Comment mode stays on the page. The page's own Edit
(next section) is what a node without an editor falls back to.

Every editor has the same frame (`EditorShell.tsx`): undo and redo, the
type's toolbar, the save state and Done along the top, an optional inspector
on the right. The editing state is `useNodeSpecEditor.ts`:

* **Undo and redo.** Each change makes a new version of the spec without
  touching the old one; the parts that did not change are shared, so a deep
  history is cheap. A run of keystrokes in one field is one step (until
  another field, a pause of two seconds, or an undo). A new change clears what
  could be redone. The history keeps 200 steps. Cmd/Ctrl+Z undoes,
  Shift+Cmd/Ctrl+Z and Ctrl+Y redo, while focus is in the editor; a text field
  with its own undo (a rich-text field) keeps the keys.
* **Saving.** The editor saves by itself 0.7 s after the last change, and at
  once when focus leaves it, the window is hidden, Done is pressed or the
  editor closes. A save sends the whole spec and the version it was edited
  from. The type's `normalize` checks it as it checks the assistant's
  writes. The answer carries the spec as it was kept, but the editor does not
  put it under the person's hands (an empty row the person just added would
  vanish); the page after Done shows what was kept. The saves of one stretch
  of editing share one history version, so "undo that" (`revert`) goes back a
  stretch, not a keystroke.
* **Conflicts.** When the assistant revised the node while it is open, the
  editor takes the new version if nothing is unsaved (as a step that can be
  undone). With unsaved work, autosave stops and a bar offers "Take theirs"
  (also undoable, so the person's own work is one undo away) or "Keep mine"
  (saved over the other version). A save the server refuses because the node
  moved on (409) ends in the same bar. Done does not drop unsaved work
  silently: when the save fails it says so and offers to leave anyway.

Charts are made in one shared dialog (`editors/charts/ChartEditor.tsx`): the
kind (columns, bars, line, area, pie, donut, columns and bars stacked),
title, unit, note, the data in a small grid (a block pasted from a
spreadsheet app fills it) or taken from a sheet's columns, the colours, and a
live preview. It hands back exactly the JSON `parse_chart`
(`dodaios/artifacts/report_blocks.py`) reads, checked by the same rules
(`charts/chartModel.ts`), so every type that holds charts draws them with the
one renderer.

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

## The `whiteboard` tool

The assistant draws on whiteboards through a second tool
(`dodaios/plugins/tool/whiteboard.py`). It does not write the scene: it
sends actions, and `dodaios/nodes/board/ops.py` turns them into valid
elements.

| Operation | What it does |
|-----------|--------------|
| `guide` | Returns the reference of every action, with short examples. |
| `list` | Returns the whiteboards. |
| `create` | Makes a board from `title`, and optionally a `mermaid` flowchart, a `diagram` or `actions`. |
| `read` | Returns what is on a board: each thing's id, type, label, box, colours, frame and connections. `query`, `ids` and `raw` narrow it. |
| `edit` | Runs `actions` on a board (also `mermaid`, `diagram`, a new `title`). |
| `duplicate` | Makes a copy of a board. |
| `revert` | Puts the previous version back. |

An action is `{"do": NAME, ...}`. The actions are `add`, `update`,
`delete`, `move`, `resize`, `connect`, `group`, `ungroup`, `frame`, `align`,
`distribute`, `layout` (flow, tree, mindmap, grid), `diagram`, `mermaid`,
`style`, `order`, `lock`, `unlock`, `clear`, `background` and `grid`.

The rules the actions keep:

- All or nothing. When one action fails, the error names its index and
  what to fix, and the board does not change.
- An id the model gives is kept, so one call can add two boxes and connect
  them. Other things get short ids such as `note-3`; an arrow of a diagram
  is `from:to`.
- A thing without a position goes to a free place right of the content, and
  things added in one call flow in rows. `near`, `right_of`, `below` and
  `inside` place it next to an element or in a frame. `below` and `above`
  line up the left edges with the element, `right_of` and `left_of` the
  tops. Nothing new overlaps what is there.
- An arrow is bound to the shapes it joins. When a shape moves, its arrows
  are drawn again; when it is deleted, they go too.
- The board looks finished: clean lines (roughness 0) and the editor's sans
  font, boxes with rounded corners, a soft fill under a darker stroke of the
  same colour. A model that wants the sketchy look asks for `roughness` 1 or
  `font: hand`.
- The board looks the same everywhere: one width per kind of shape in a
  diagram, the editor's 20 px grid and colour palette, sticky notes as
  yellow boxes, groups as frames. A height follows its own label; boxes in
  one row of a grid, or in one group, share the row's height. A box whose
  label has several lines may run wider (300 px of text instead of 240), so
  a stat card does not become a tall column. Notes or boxes of one kind
  added in one `add` get one size.
- A grid of frames is a dashboard: the frames stand in top-aligned rows,
  40 px apart, the frames of a row stretched to one height, and each frame's
  contents start at its top-left padding.
- Every element an action creates carries `customData: {"by": "assistant"}`
  (merged with what is there), so the editor can show the assistant's new
  elements arriving.
- After every `create` and `edit` the result ends with `Check:` lines from
  `dodaios/nodes/board/check.py`, read from the final board: things that
  overlap, a label that does not fit its box, an element sticking out of its
  frame, frames in one row whose tops differ, a box far larger than its
  label, an arrow through a shape. Each line names the ids and the fix; one
  line says when all is clear. Only what the call made or changed is
  checked, not the person's own drawing.
- An edit runs under the node's lock on the scene as it is stored. Every
  element it changes gets a new version, so the open editor merges it with
  the person's drawing. Each edit is one history version.

`POST /api/nodes/{id}/whiteboard` runs the same actions for scripts and
other agents.

| Part | File |
|------|------|
| Element factory, palette, fonts, fractional indices | `dodaios/nodes/board/elements.py` |
| Layouts and free places | `dodaios/nodes/board/layout.py` |
| Diagrams, the older grammar | `dodaios/nodes/board/convert.py` |
| Mermaid flowcharts | `dodaios/nodes/board/mermaid.py` |
| Actions and the reading | `dodaios/nodes/board/ops.py` |
| The self-check | `dodaios/nodes/board/check.py` |

## The library

The Nodes section shows one list of cards. It holds the typed nodes and
everything older runs left behind. `dodaios/nodes/library.py` builds the list:

| Source | Card type | `origin` |
|--------|-----------|----------|
| A typed node | Its own type | `node` |
| A living page (`__living-page__` run) | `sheets` | `living` |
| A report page (`__report__` run) | `docs` | `report` |
| Any other HTML page a run wrote | `docs` | `page` |
| A picture or an SVG | `docs` | `file` |
| A PDF | `docs` | `file` |
| A running run that still builds its page | `docs` | `build` |
| A run that left no page, picture or PDF | `output` | `run` |

Only a card with the origin `node` has a spec and can be renamed, copied or
reverted. The other cards are files; they are opened, and deleted through
`/api/outputs`. A node of a type the app no longer has (the old `design`
type, "Visuals") does not read as a node; its run is listed like any other
run, so its page stays in the library as a `docs` page.

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

## A node opened from a conversation

A click on a node's card in a chat does not leave the chat for the Nodes
section. It opens the node window: a window over the app, with a margin on
every side. The node is on the left, on the same stage the Nodes section has.
The conversation the click came from is on the right, with its composer.

| In the window | What it does |
|---------------|--------------|
| Edit, Comment, Share, the overflow menu | The same as on the stage of the Nodes section. |
| "Ask to change it" | Writes the start of the request into the composer beside the node. Nothing is sent. |
| The seam between node and conversation | Drag it to resize the conversation. The width is remembered. |
| The panel button | Puts the conversation away or brings it back. The choice is remembered. |
| The arrows button | "Open in Nodes": closes the window and opens the node in the Nodes section. |
| Left and right arrow keys | Go to the previous or next page this conversation made. |
| Escape, the close button, a click beside the window | Close it. |

A card clicked in the conversation beside the node puts that node in the
window. The assistant's next revision shows in the open node after a few
seconds, because the stage watches the node. If comments were left on the
node and not sent, the window asks before it closes: send them, drop them, or
stay.

In a window too narrow for two columns, the conversation is closed at first
and slides over the node when the panel button opens it.

The same window opens from the file list in the assistant's panel, from a
page link in an answer, and from a result card. A change of section closes
it. The store is `store/nodePeek.ts`; `openNodePeek(ref, { chat })` opens a
`slug::path` address beside the chat store it is given.

The window is on screen at the click. Four things make that so:

| What | Where |
|------|-------|
| The window's code is fetched while the app idles after its start, and again when the pointer reaches a card. | `preloadNodePeek` in `peek/peekFrame.ts` |
| A click that is faster than that still gets the frame, the node's name and a close button at once. The content takes its place in the same frame. | `NodePeekFrame` in `peek/NodePeekHost.tsx` |
| The conversation is not drawn a second time. The front page offers the element its conversation is drawn in, and the window moves that element beside the node and puts it back when it closes. The reader keeps their place. | `lender` in `store/nodePeek.ts`, `peek/moveKeepingPlace.ts`, `views/HomeView.tsx` |
| The first frame is the window and the node. The conversation follows right after it. Nothing fades in and nothing is blurred. | `peek/NodePeekWindow.tsx` |

A conversation the front page does not offer (a pane's chat in the IDE, an
agent's chat) is drawn in the window, after the node.

The stage loads a typed node's page once. The watcher's first answer names
the revision that page already shows; only a later answer draws the page
again.

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
| `PUT /api/nodes/{id}/spec` | Body `{"spec", "base_version"}`. A type editor's save of the whole spec, made from `base_version` (`null`: whatever the node holds). Answers `{"version", "updated_at", "spec"}` with the spec as the type kept it. `409` `{"detail", "version", "updated_at", "spec"}` when the node is no longer at `base_version`; `422` with the type's sentence when the spec is refused (and for a whiteboard). |
| `POST /api/nodes/{id}/preview` | Body `{"spec"}`. The node's page drawn from that spec without saving it, served like the node's page (scripts run, network shut, not cached). `422` when the spec is refused. |
| `POST /api/nodes/{id}/revert` | Puts the previous version back and returns the card. |
| `POST /api/nodes/{id}/upkeep/stop` | Stops the upkeep and returns the node. |
| `POST /api/nodes/{id}/upkeep/resume` | Body `{"every_minutes"?}`. Starts the upkeep again and returns the node. |
| `GET /api/nodes/{id}/scene` | A whiteboard's scene: `{"version", "updated_at", "scene"}`. |
| `PUT /api/nodes/{id}/scene` | Body `{"scene"}`. The editor's save, merged with the stored scene. Answers `{"version", "updated_at", "merged"}`, and `"scene"` (the merged scene) when `merged` is true. |
| `POST /api/nodes/{id}/files` | Body `{"dataURL", "id"?}`. Keeps a picture for a whiteboard. Without `id` the id is the SHA-1 of the bytes. Answers `{"id", "mimeType"}`. |
| `GET /api/nodes/{id}/files/{fileId}` | A whiteboard picture's bytes, with the type its bytes have, cached for good and under `Content-Security-Policy: default-src 'none'`. |
| `POST /api/nodes/{id}/whiteboard` | Body `{"actions": [...]}`: the `whiteboard` tool's actions, for scripts and other agents. All actions or none; saved as one revision. Answers `{"version", "report", "summary", "check"}`: one report line per action, `{"elements", "bounds"}` of the board, and the self-check lines for what the actions made or changed (empty when all is clear). |
| `DELETE /api/nodes/{id}` | Stops the upkeep, then removes the node, its page and its history. Returns `{"deleted": true}`. |

Errors: `404` for an id that is not a node. `400` with the reason as one
sentence for a request the store refuses (an unknown type, an empty title, no
earlier version, no `track` to resume). `422` for a body of the wrong shape.
`503` when the upkeep cannot be scheduled because the task scheduler is not
running. The whiteboard routes answer `422` for a node of another type, `409`
for a picture id that already holds a different picture, and `413` for a body
over its ceiling (a scene of 8.5 MB, a picture of about 7 MB as base64, 2 MB
of actions). The spec routes take a body of up to about 4 MB.

The person's editors write a node's content through these routes: a
whiteboard's scene, every other type's spec (`/spec`), one value typed into a
page (`/edit`); scripts may run the `whiteboard` tool's actions. The
assistant writes nodes through the `node` tool.

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
| Whiteboard scene, page, pictures, actions | `dodaios/nodes/board/` |
| Upkeep | `dodaios/nodes/refresh.py` |
| The library's cards | `dodaios/nodes/library.py` |
| The tools | `dodaios/plugins/tool/node.py`, `dodaios/plugins/tool/whiteboard.py` |
| HTTP API | `dodaios/ui/web/nodes_routes.py` |
| Card model of the frontend | `dodaios/ui/web/frontend/src/components/nodes/nodeModel.ts` |
| The node window over a conversation | `dodaios/ui/web/frontend/src/components/nodes/peek/` |
