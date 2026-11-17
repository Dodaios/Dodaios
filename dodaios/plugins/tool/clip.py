"""``clip`` — the assistant edits a person's video clips.

A clip is a node of type ``motion`` (:mod:`dodaios.nodes.kinds.motion`): a
main track of video pieces and animated cards, tracks of text, pictures and
sound above it, and captions. The person edits it in the app's clip editor;
the assistant edits the same spec through this tool, so every cut it makes is
on the person's timeline (as an undoable step of the open editor) and every
cut the person makes is what the assistant reads next.

Why a tool of its own next to ``node``: a clip is not written as a spec by
hand. The model sends ACTIONS ("split v3 at 4.2 s", "remove these silences",
"add a title layer"), and :mod:`dodaios.nodes.clip.ops` does the timeline
arithmetic (source offsets, the magnetic main track, keys at a cut, captions
moving with a removed stretch). The heavy work has operations of its own:
``import`` takes files into the clip's library, ``transcribe`` and
``captions`` hear what is said, ``silences`` finds the pauses, ``look`` shows
frames as pictures, ``export`` writes the MP4 (:mod:`dodaios.nodes.clip`).

Router-tier, risk ``monitor``: a call writes one node in the run archive (and
its media files, and an export) and posts its card. It never sends anything,
never spawns a worker and never calls a model.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.nodes.clip import ops
from dodaios.nodes.kinds import motion
from dodaios.nodes.kinds import motion_media as mm
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NodeError
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.create_artifact import _called_in_background
from dodaios.plugins.tool.living_page import page_card, post_card, session_of

log = logging.getLogger(__name__)

_OPERATIONS: Final[tuple[str, ...]] = (
    "guide",
    "list",
    "create",
    "read",
    "edit",
    "import",
    "transcribe",
    "captions",
    "silences",
    "look",
    "export",
    "revert",
)
#: Operations that name one existing clip.
_ON_ONE_CLIP: Final[frozenset[str]] = frozenset(_OPERATIONS) - {"guide", "list", "create"}
DEFAULT_TITLE: Final[str] = "Clip"
#: How much of a reading or a transcript goes back; more would crowd the turn.
MAX_READ_CHARS: Final[int] = 40_000
#: Pictures per look call: the MCP bridge passes at most four to the model.
MAX_PICTURES: Final[int] = 4
#: Frames one look may ask for (four contact sheets of four).
MAX_LOOK_FRAMES: Final[int] = 16
#: How long an export call waits before it hands back a job to ask about later.
EXPORT_WAIT_S: Final[float] = 150.0
#: The export job of the clip tool → the ledger job that reports it.
_LEDGER: dict[str, str] = {}

GUIDE: Final[str] = """\
Clip editing. A clip has a MAIN track (pieces back to back: video pieces and \
animated cards), tracks above it (text, overlay pictures/videos, audio), and captions. \
Times are seconds on the clip's clock ("4.2" or "1:04.5"); 'in' is a time in the source file.

Operations: create (title, format wide|tall|square|portrait, files, actions), read (the \
timeline with every id: ALWAYS read before editing a clip you did not just make), \
import (files: absolute paths; place: true also puts them on the timeline), edit \
(actions, all or none), transcribe (id of a piece, or media + in/out: every word with \
its time), captions (auto captions from the speech: style, position, size), silences \
(id of a video piece: pauses; apply: true cuts them out), look (times: frames as pictures), \
export (preset 720p|1080p|2160p, fps 24|30|60; a long one returns a job: call export with \
job to ask), revert. Media is named by its id or its exact file name.

Actions ({"do": NAME, ...}):
- add_clip: media, track main (default for video/picture) | overlay | audio | a track id, \
at (time) or index (main), in, out or seconds, speed (0.25-4), volume (0-1), muted, \
fit cover|contain, zoom, x, y (offset % of frame), rotate, opacity, crop {l,t,r,b} \
(fractions), filter none|vivid|warm|cool|mono|fade|noir|film, color {brightness, contrast, \
saturation, warmth} (-100..100), transition. Overlay: x, y (centre %), w (width %), radius.
- add_scene: type title|text|bullets|stat|bars|quote|steps|image|chart|end + its fields \
(node guide 'motion'), index or at.
- add_text: text, start, seconds, style title|subtitle|body|label|caption|quote, x, y \
(centre %), size (px), color, bg none|shadow|box|pill, font sans|serif|mono, align, \
anim fade|rise|pop|slide|zoom|type|none, out fade|rise|pop|slide|zoom|none, track.
- add_music: media, start (0), seconds (to the end), in, volume (0.25), fade_in (1), \
fade_out (2), duck (true: 30 % while speech plays).
- split: id, at.  trim: id, start and/or end (new edges), or in (slip the source).
- delete: ids, ripple (main track: always closes the gap, and text/overlays/captions \
after it move with it; on a track ripple: true pulls that track's later items).
- move: id, index (main) or to (time) and track (track items).
- set: id + any fields above (null removes one).  duplicate: id.
- keyframe: id, t (inside the item), zoom/x/y/rotate/opacity, or remove: true.
- transition: id (the piece it leads into), kind cut|fade|slide|zoom|wipe|dip|blur.
- captions: items [{start, end, text}], style clean|bold|karaoke|boxed|none, position \
bottom|middle|top, size s|m|l.  caption_style: style/position/size.  caption_edit: index + \
text/start/end, or remove: index.
- remove_silences: id, silences [[start, end], ...] in SOURCE seconds (from 'silences').
- format: format, theme, accent, loop.
Example: {"do":"split","id":"v1","at":3.2} {"do":"add_text","text":"3 MISTAKES",\
"start":0,"seconds":2,"style":"title","anim":"pop","y":30}

Making a clip people finish watching (do all of it, not some):
1. Read, then transcribe the footage. Know what is said before cutting.
2. Cut the dead air: silences (apply: true), then filler words ("um", "uh", "like", \
the fillers of the spoken language, a sentence started twice): find their times in the \
transcript, split around them and delete the piece. Keep the best take of a repeated line.
3. Hook in the first 1.5-2 s: start on the strongest line (move it first if needed) and \
put a bold text layer of 2-5 words on it (style title, anim pop, y 25-35).
4. Pacing: a visual change every 2-4 s: a cut, a zoom key (1.0 -> 1.08 over the piece, \
or a punch-in to 1.15 on a key sentence), an overlay, a text. No piece over 6 s unchanged.
5. Captions on whenever someone speaks: operation captions, style karaoke or bold, \
position bottom. Fix misheard words with caption_edit (names, brands, numbers).
6. 9:16 (tall) for TikTok, Reels and Shorts, 30-60 s. Keep text inside the safe zone: \
x 12-88 %, y 12-76 % (the apps cover the edges and the bottom).
7. Music: add_music at volume 0.2-0.3 with duck true and fades; never louder than the voice.
8. End on a clear last beat: the payoff line, or an end card / text with the next step.
9. Look at 4 or more frames (always the first second) before you answer. Fix what is \
weak: unreadable or covered text, a black or empty frame, captions out of the safe zone, \
a slow start. Then export if the person wants the file.
"""

#: What a look asks the model to judge.
_JUDGE_IT: Final[str] = (
    "Judge each frame as a viewer scrolling past would. Weak means: no hook in the first "
    "two seconds; text too small, too long or covered (keep it inside x 12-88 %, y 12-76 % "
    "on a tall clip); captions missing where someone speaks or out of the safe zone; a "
    "black, empty or frozen frame; the same picture too long. Fix every weak point with "
    "'edit', look again, and answer only when you would post it yourself."
)
#: What a create or an edit tells the model to do before it answers.
_CHECK_IT: Final[str] = (
    "Before you answer, call 'look' on this clip and judge the frames; fix what is weak."
)


def _json_value(value: Any) -> Any:
    """``value``, parsed when a caller sent an object or a list as JSON text."""
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:  # not JSON after all: the check that reads it says what is needed
            return value
    return value


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _language(ctx: Any, args: dict[str, Any]) -> str:
    config = getattr(ctx, "config", None)
    stamped = str(config.get("output_language") or "") if isinstance(config, dict) else ""
    return (stamped or str(args.get("language") or "") or "en").strip().lower()[:8]


def _number(value: Any, what: str, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NodeError(f"'{what}' must be a number.") from exc


def _summary(node: Node) -> dict[str, Any]:
    spec = node.spec if isinstance(node.spec, dict) else {}
    return {
        "id": node.id,
        "title": node.title,
        "version": node.version,
        "updated_at": datetime.fromtimestamp(node.updated_at)
        .astimezone()
        .isoformat(timespec="seconds"),
        "format": spec.get("format"),
        "seconds": mm.duration(spec) if spec.get("scenes") else 0,
        "media": len(spec.get("media") or {}),
    }


def _actions_of(args: dict[str, Any]) -> list[dict[str, Any]]:
    given = _json_value(args.get("actions"))
    if given is None:
        return []
    if isinstance(given, dict):
        given = [given]
    if not isinstance(given, list):
        raise NodeError('\'actions\' must be a list of objects like {"do": "split", ...}.')
    return given


def _placements(entries: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Actions that put newly imported files on the timeline, in the order given."""
    actions: list[dict[str, Any]] = []
    for media_id, entry in entries:
        if entry.get("kind") == "audio":
            actions.append({"do": "add_music", "media": media_id})
        else:
            actions.append({"do": "add_clip", "media": media_id})
    # Music is placed last, so it runs to the end of the pictures.
    return [a for a in actions if a["do"] == "add_clip"] + [
        a for a in actions if a["do"] == "add_music"
    ]


def _sheets(shots: list[bytes], times: list[float]) -> list[str]:
    """Frames as base64 JPEGs: one each up to four, else sheets of four with their times."""
    if len(shots) <= MAX_PICTURES:
        return [base64.b64encode(shot).decode("ascii") for shot in shots]
    from PIL import Image, ImageDraw  # noqa: PLC0415 — only a long look needs it

    pictures: list[str] = []
    cell = 520
    for first in range(0, len(shots), 4):
        group = list(zip(shots[first : first + 4], times[first : first + 4], strict=False))
        sheet = Image.new("RGB", (2 * cell + 48, 2 * (cell + 28) + 36), (96, 96, 96))
        pen = ImageDraw.Draw(sheet)
        for index, (data, at) in enumerate(group):
            left = 16 + (index % 2) * (cell + 16)
            top = 12 + (index // 2) * (cell + 40)
            pen.text((left, top), f"{at:.2f} s", fill=(255, 255, 255))
            with Image.open(io.BytesIO(data)) as shot:
                frame = shot.convert("RGB")
                frame.thumbnail((cell, cell), Image.Resampling.LANCZOS)
            sheet.paste(frame, (left + (cell - frame.width) // 2, top + 22))
        buffer = io.BytesIO()
        sheet.save(buffer, format="JPEG", quality=82, optimize=True)
        pictures.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
    return pictures[:MAX_PICTURES]


def _default_times(total: float) -> list[float]:
    """Where a look stands when not told: the hook, and spread over the rest."""
    if total <= 1:
        return [total / 2]
    marks = [0.6, total * 0.3, total * 0.55, total * 0.8, max(0.0, total - 0.4)]
    return sorted({round(min(mark, total - 0.05), 2) for mark in marks})


def _import_one(media: Any, run_dir: Path, path: Path) -> tuple[str, dict[str, Any]]:
    """One file into the clip's library (blocking: decodes, may convert)."""
    if not path.is_file():
        raise NodeError(f"There is no file at {str(path)!r}.")
    return media.import_media(run_dir, path, path.name)


class ClipTool:
    """Create, read, cut, caption, look at and export the person's video clips."""

    name: str = "clip"
    risk_tier: str = "monitor"
    description: str = (
        "Edit a video CLIP (a node of type motion; the app's Clips): a main track of video "
        "pieces and cards, text/overlay/audio tracks and captions, the same timeline the "
        "person edits by hand. 'create' (title, format, files to import); 'import' files; "
        "'read' the timeline with ids; 'edit' with actions (add_clip, split, trim, delete, "
        "move, set, keyframe, transition, add_text, add_music, captions, remove_silences, "
        "...); 'transcribe' what is said; 'captions' makes subtitles from speech; "
        "'silences' finds pauses; 'look' shows frames; 'export' writes the MP4; 'revert'. "
        "Call 'guide' once before your first edit: it has every action and how to make a "
        "clip people finish watching."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(_OPERATIONS)},
            "clip": {
                "type": "string",
                "description": "All but guide/list/create: the clip's node id or title.",
            },
            "title": {"type": "string", "description": "create: the clip's title."},
            "format": {
                "type": "string",
                "enum": list(motion.FORMATS),
                "description": "create: wide 16:9, tall 9:16 (short-form), square, portrait 4:5.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "create, import: absolute paths of videos, sounds or pictures.",
            },
            "place": {
                "type": "boolean",
                "description": "import: also put the files on the timeline.",
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"do": {"type": "string", "enum": list(ops.ACTIONS)}},
                    "required": ["do"],
                },
                "description": "create, edit: the actions, run in order, all or none (see guide).",
            },
            "id": {
                "type": "string",
                "description": "transcribe, silences: a main-track piece's or a track item's id.",
            },
            "media": {
                "type": "string",
                "description": "transcribe: a library file (id or name) instead of 'id'.",
            },
            "in": {
                "type": "number",
                "description": "transcribe with media: from (source seconds).",
            },
            "out": {"type": "number", "description": "transcribe with media: to (source seconds)."},
            "style": {
                "type": "string",
                "enum": list(mm.CAPTION_STYLES),
                "description": "captions.",
            },
            "position": {
                "type": "string",
                "enum": list(mm.CAPTION_PLACES),
                "description": "captions.",
            },
            "size": {"type": "string", "enum": list(mm.CAPTION_SIZES), "description": "captions."},
            "min_silence": {
                "type": "number",
                "description": "silences: the shortest pause that counts (default 0.5 s).",
            },
            "pad": {
                "type": "number",
                "description": "silences: speech kept on each side of a pause (default 0.12 s).",
            },
            "apply": {"type": "boolean", "description": "silences: cut the pauses out right away."},
            "times": {
                "type": "array",
                "items": {"type": "number"},
                "description": f"look: the moments to see (seconds), up to {MAX_LOOK_FRAMES}.",
            },
            "preset": {
                "type": "string",
                "enum": ["720p", "1080p", "2160p"],
                "description": "export.",
            },
            "fps": {"type": "integer", "enum": [24, 30, 60], "description": "export."},
            "job": {"type": "string", "description": "export: ask about a running export."},
            "language": {
                "type": "string",
                "description": "transcribe, captions: the spoken language (default: detected).",
            },
        },
        "required": ["operation"],
    }

    def __init__(self, store: NodeStore | None = None) -> None:
        self._store = store

    def _nodes(self) -> NodeStore:
        if self._store is None:
            self._store = NodeStore()
        return self._store

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        operation = str(args.get("operation") or "").strip().lower()
        if operation not in _OPERATIONS:
            return ToolResult(False, "", f"'operation' must be one of {', '.join(_OPERATIONS)}.")
        store = self._nodes()
        try:
            if operation == "guide":
                return ToolResult(True, GUIDE)
            if operation == "list":
                return await self._list(store)
            if operation == "create":
                return await self._create(store, args, ctx)
            node = await self._find(store, args, operation)
            handler = getattr(self, f"_{operation}")
            return await handler(store, node, args, ctx)
        except NodeError as exc:  # the model's call to fix; the error says how
            return ToolResult(False, "", str(exc))
        except OSError as exc:
            log.warning("clip %s: archive not writable", operation, exc_info=True)
            return ToolResult(False, "", f"The clip could not be saved: {exc}")
        except (ValueError, RuntimeError) as exc:
            # The media, speech and export modules say what went wrong in one sentence.
            log.info("clip %s failed: %s", operation, exc)
            return ToolResult(False, "", str(exc) or f"The {operation} did not work.")

    # ---------------------------------------------------------- helpers

    async def _find(self, store: NodeStore, args: dict[str, Any], operation: str) -> Node:
        reference = _text(args.get("clip") or args.get("node"))
        if reference is None:
            raise NodeError(f"'clip' is required for {operation}: the clip's id or exact title.")
        node = await asyncio.to_thread(store.find, reference)
        if node is None:
            raise NodeError(
                f"No clip with the id or title {reference!r}; call operation 'list' to see them."
            )
        if node.type != "motion":
            raise NodeError(f"'{node.title}' is a {node.type} node, not a clip.")
        return node

    @staticmethod
    async def _dir(store: NodeStore, node: Node) -> Path:
        run_dir = await asyncio.to_thread(store.dir_of, node.id)
        if run_dir is None:
            raise NodeError(f"The folder of clip {node.id} is missing.")
        return run_dir

    async def _apply(
        self,
        store: NodeStore,
        node: Node,
        actions: list[dict[str, Any]],
        *,
        media: dict[str, dict[str, Any]] | None = None,
        title: str | None = None,
    ) -> tuple[Node, list[str]]:
        """Run actions on the clip as stored now, under its lock, and save the result."""

        def run() -> tuple[Node, list[str]]:
            # A save from the editor cannot land between this read and the write.
            with store.locked(node.id):
                current = store.get(node.id)
                if current is None:
                    raise NodeError(f"Clip {node.id} is gone.")
                spec, report = ops.apply_actions(current.spec, actions, media_lookup=media)
                return store.update(node.id, spec=spec, title=title), report

        return await asyncio.to_thread(run)

    async def _card(self, ctx: Any, node: Node) -> bool:
        if _called_in_background(ctx):
            return False
        return await post_card(
            session_of(ctx), page_card(node.title, node.visual_id, node_type=node.type)
        )

    async def _import_files(
        self, store: NodeStore, node: Node, files: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        from dodaios.nodes.clip import media  # noqa: PLC0415 — PyAV loads on demand

        if isinstance(files, str):
            files = [files]
        if not isinstance(files, list) or not files:
            raise NodeError(
                "'files' must be a list of absolute paths of videos, sounds or pictures."
            )
        run_dir = await self._dir(store, node)
        imported: list[tuple[str, dict[str, Any]]] = []
        for raw in files:
            path = PurePath(str(raw))
            if not path.is_absolute():
                raise NodeError(f"{raw!r} is not an absolute path; give the full path of the file.")
            imported.append(await asyncio.to_thread(_import_one, media, run_dir, Path(path)))
        return imported

    # ---------------------------------------------------------- operations

    async def _list(self, store: NodeStore) -> ToolResult:
        nodes = await asyncio.to_thread(store.list_nodes)
        clips = [_summary(n) for n in nodes if n.type == "motion"]
        if not clips:
            return ToolResult(True, "There are no clips yet; 'create' makes one.")
        return ToolResult(True, clips)

    async def _create(self, store: NodeStore, args: dict[str, Any], ctx: Any) -> ToolResult:
        title = _text(args.get("title")) or DEFAULT_TITLE
        film_format = str(args.get("format") or "tall").strip().lower()
        if film_format not in motion.FORMATS:
            raise NodeError("'format' must be one of " + ", ".join(motion.FORMATS) + ".")
        actions = _actions_of(args)
        spec = {"format": film_format, "scenes": [{"type": "title"}]}
        node = await asyncio.to_thread(
            store.create, type="motion", title=title, spec=spec, language=_language(ctx, args)
        )
        report: list[str] = []
        files = _json_value(args.get("files"))
        imported: list[tuple[str, dict[str, Any]]] = []
        try:
            if files:
                imported = await self._import_files(store, node, files)
                report += [
                    f"imported {entry['name']} as {mid} ({entry['kind']})"
                    for mid, entry in imported
                ]
                if not actions:
                    actions = _placements(imported)
            if actions:
                node, done = await self._apply(store, node, actions, media=dict(imported))
                report += done
            elif imported:
                node, _ = await self._apply(store, node, [], media=dict(imported))
        except (NodeError, ValueError, RuntimeError) as exc:
            # The clip exists either way; the model hears what to fix next.
            report.append(f"Not done: {exc}")
        job_id = jobs.start(
            "artifact",
            ctx=ctx,
            title=node.title,
            target=f"node:{node.id}",
            meta={"node_id": node.id},
        )
        jobs.finish(job_id, "done", summary="Clip.", result_ref=f"artifact:{node.visual_id}")
        shown = await self._card(ctx, node)
        where = "Its card is in the chat" if shown else "It is in the Nodes section"
        text = (
            f"Created the clip '{node.title}' (clip id {node.id}, version {node.version}). "
            f"{where}; the person can edit it in the clip editor.\n"
            + "\n".join(report)
            + f"\n\n{ops.describe(node.spec)}\n\n{_CHECK_IT}"
        )
        return ToolResult(True, jobs.with_job_id(text, job_id, ctx))

    async def _read(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        text = f"Clip '{node.title}' (id {node.id}, version {node.version}).\n" + ops.describe(
            node.spec
        )
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n… (cut: the clip is longer than one reading)"
        return ToolResult(True, text)

    async def _edit(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        actions = _actions_of(args)
        if not actions:
            raise NodeError("'edit' needs 'actions'; call 'guide' for the reference.")
        updated, report = await self._apply(store, node, actions, title=_text(args.get("title")))
        await self._card(ctx, updated)
        total = mm.duration(updated.spec)
        return ToolResult(
            True,
            f"Clip '{updated.title}' is now version {updated.version}, {total:.2f} s long.\n"
            + "\n".join(report)
            + f"\n{_CHECK_IT}",
        )

    async def _import(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        imported = await self._import_files(store, node, _json_value(args.get("files")))
        actions = _placements(imported) if args.get("place") else []
        updated, report = await self._apply(store, node, actions, media=dict(imported))
        lines = []
        for media_id, entry in imported:
            length = f", {float(entry['seconds']):.2f} s" if entry.get("seconds") else ""
            sound = ", with sound" if entry.get("audio") and entry.get("kind") == "video" else ""
            lines.append(f"- {media_id}: {entry['name']} ({entry['kind']}{length}{sound})")
        placed = ("\n" + "\n".join(report)) if args.get("place") else ""
        await self._card(ctx, updated)
        return ToolResult(
            True,
            f"Imported into the clip's library (version {updated.version}):\n"
            + "\n".join(lines)
            + placed,
        )

    async def _transcribe(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        from dodaios.nodes.clip import (  # noqa: PLC0415 — the model loads on demand
            media,
            transcribe,
        )

        spec = node.spec
        library = spec.get("media") or {}
        start = end = None
        timeline: dict[str, float] | None = None
        if _text(args.get("id")):
            timeline = ops.piece_times(spec, str(args["id"]))
            if not timeline["media"]:
                raise NodeError(f"'{args['id']}' is a card or a text; it has nothing to hear.")
            media_id = str(timeline["media"])
            start = timeline["in"]
            end = start + (timeline["end"] - timeline["start"]) * timeline["speed"]
        else:
            ref = _text(args.get("media"))
            if ref is None:
                raise NodeError("transcribe needs 'id' (a piece) or 'media' (a library file).")
            media_id = next(
                (k for k, e in library.items() if k == ref.lower() or e.get("name") == ref), ""
            )
            if not media_id:
                raise NodeError(f"The clip's library has no media {ref!r}; 'read' lists it.")
            start = _number(args.get("in"), "in", 0.0)
            end = _number(args.get("out"), "out")
        entry = library.get(media_id) or {}
        path = media.media_file(await self._dir(store, node), str(entry.get("file") or ""))
        if path is None:
            raise NodeError(f"The file of media {media_id} is missing from the clip's folder.")
        heard = await asyncio.to_thread(
            transcribe.transcribe_file, path, start or 0.0, end, _text(args.get("language"))
        )
        words = heard.get("words") or []
        if timeline is not None:
            tokens = []
            for word in words:
                at = timeline["start"] + (float(word["s"]) - timeline["in"]) / timeline["speed"]
                if timeline["start"] - 0.05 <= at <= timeline["end"]:
                    tokens.append(f"{word['w']}@{at:.2f}")
            clock = "clip time (split/delete use it)"
        else:
            tokens = [f"{word['w']}@{float(word['s']):.2f}" for word in words]
            clock = "source time of the file"
        text = (
            f"Language {heard.get('language') or '?'}; {len(words)} words; times are {clock}.\n"
            f"Text: {heard.get('text', '').strip()}\nWords: " + " ".join(tokens)
        )
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + " … (cut: transcribe a shorter range)"
        return ToolResult(True, text)

    async def _captions(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        from dodaios.nodes.clip import captions  # noqa: PLC0415 — the model loads on demand

        run_dir = await self._dir(store, node)
        words = await asyncio.to_thread(
            captions.timeline_words, node.spec, run_dir, _text(args.get("language"))
        )
        if not words:
            raise NodeError(
                "No speech was heard in the clip's video pieces or voice tracks; captions need "
                "spoken words (or write them with the 'captions' action)."
            )
        lines = captions.caption_lines(words, str(node.spec.get("format") or "wide"))
        action: dict[str, Any] = {"do": "captions", "items": lines}
        for key in ("style", "position", "size"):
            if args.get(key):
                action[key] = args[key]
        updated, _ = await self._apply(store, node, [action])
        await self._card(ctx, updated)
        shown = "\n".join(
            f"[{n}] {float(line['start']):.2f}-{float(line['end']):.2f} {line['text']}"
            for n, line in enumerate(lines[:12])
        )
        more = f"\n… {len(lines) - 12} more" if len(lines) > 12 else ""
        return ToolResult(
            True,
            f"{len(lines)} caption lines from {len(words)} words (version {updated.version}). "
            "Check names, brands and numbers; fix them with caption_edit.\n" + shown + more,
        )

    async def _silences(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        from dodaios.nodes.clip import media, silence  # noqa: PLC0415 — PyAV loads on demand

        piece_id = _text(args.get("id"))
        if piece_id is None:
            raise NodeError("silences needs 'id': a video piece of the main track ('read').")
        times = ops.piece_times(node.spec, piece_id)
        entry = (node.spec.get("media") or {}).get(str(times["media"])) or {}
        if entry.get("kind") not in ("video", "audio"):
            raise NodeError(f"'{piece_id}' is not a piece of a video or a sound.")
        path = media.media_file(await self._dir(store, node), str(entry.get("file") or ""))
        if path is None:
            raise NodeError(f"The file of '{piece_id}' is missing from the clip's folder.")
        source_end = times["in"] + (times["end"] - times["start"]) * times["speed"]
        spans = await asyncio.to_thread(
            silence.find_silences,
            path,
            times["in"],
            source_end,
            _number(args.get("min_silence"), "min_silence", 0.5) or 0.5,
            _number(args.get("pad"), "pad", 0.12) or 0.0,
        )
        if not spans:
            return ToolResult(True, f"No pauses in '{piece_id}' long enough to cut.")
        quiet = sum(b - a for a, b in spans) / times["speed"]
        listed = ", ".join(
            f"{times['start'] + (a - times['in']) / times['speed']:.2f}-"
            f"{times['start'] + (b - times['in']) / times['speed']:.2f}"
            for a, b in spans
        )
        source = [[round(a, 3), round(b, 3)] for a, b in spans]
        if args.get("apply"):
            updated, report = await self._apply(
                store, node, [{"do": "remove_silences", "id": piece_id, "silences": source}]
            )
            await self._card(ctx, updated)
            return ToolResult(
                True,
                f"{report[0]} (version {updated.version}, now {mm.duration(updated.spec):.2f} s). "
                "Read the clip again: the pieces have new ids.",
            )
        return ToolResult(
            True,
            f"{len(spans)} pause(s) in '{piece_id}', {quiet:.2f} s in all, at clip time {listed}. "
            "To cut them: edit with "
            + json.dumps({"do": "remove_silences", "id": piece_id, "silences": source})
            + " (or call silences again with apply: true).",
        )

    async def _look(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        from dodaios.nodes.clip import export  # noqa: PLC0415 — a browser, on demand

        total = mm.duration(node.spec)
        wanted = _json_value(args.get("times"))
        if wanted:
            if not isinstance(wanted, list):
                raise NodeError("'times' must be a list of seconds.")
            times = [max(0.0, min(float(t), total - 0.05)) for t in wanted[:MAX_LOOK_FRAMES]]
        else:
            times = _default_times(total)
        shots = await asyncio.to_thread(
            export.still_frames, node, await self._dir(store, node), node.spec, times, 540
        )
        pictures = await asyncio.to_thread(_sheets, shots, times)
        shown = ", ".join(f"{t:.2f}" for t in times[: len(shots)])
        return ToolResult(
            True,
            f"Frames at {shown} s of {total:.2f} s"
            + (" (four to a picture)." if len(shots) > MAX_PICTURES else ".")
            + f" {_JUDGE_IT}",
            artifacts=tuple(
                {"type": "image", "mime": "image/jpeg", "data": data} for data in pictures
            ),
        )

    async def _export(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        from dodaios.nodes.clip import export  # noqa: PLC0415 — a browser and an encoder

        job = _text(args.get("job"))
        if job is None:
            preset = str(args.get("preset") or "1080p")
            fps = int(_number(args.get("fps"), "fps", 30) or 30)
            job = await asyncio.to_thread(
                export.start_export, node, await self._dir(store, node), node.spec, preset, fps
            )
            _LEDGER[job] = jobs.start(
                "artifact",
                ctx=ctx,
                title=f"{node.title} (MP4)",
                target=f"node:{node.id}",
                meta={"node_id": node.id, "export": job},
            )
            waited = 0.0
            while waited < EXPORT_WAIT_S:
                status = export.export_status(job) or {}
                if status.get("state") != "running":
                    break
                await asyncio.sleep(1.0)
                waited += 1.0
        status = export.export_status(job)
        if status is None:
            raise NodeError(f"There is no export {job!r} (exports are kept for a few hours).")
        state = status.get("state")
        if state == "running":
            share = float(status.get("progress") or 0)
            return ToolResult(
                True,
                f"The export is still running ({share:.0%}). Ask again later with operation "
                f"'export' and job '{job}'; tell the person it is on its way.",
            )
        ledger = _LEDGER.pop(job, None)
        if state == "done":
            jobs.finish(ledger, "done", summary=f"MP4: {status.get('file')}")
            return ToolResult(
                True,
                f"Exported: {status.get('file')}. Tell the person where the file is; it also "
                "opens from the clip editor's export panel.",
            )
        jobs.finish(ledger, "failed", summary=str(status.get("error") or state))
        return ToolResult(False, "", f"The export {state}: {status.get('error') or 'stopped'}.")

    async def _revert(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        restored = await asyncio.to_thread(store.revert, node.id)
        await self._card(ctx, restored)
        return ToolResult(
            True,
            f"Clip '{restored.title}' has its earlier content again "
            f"(now version {restored.version}).",
        )


__all__ = ["GUIDE", "MAX_READ_CHARS", "ClipTool"]
