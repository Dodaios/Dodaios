"""The ``motion`` node: a short animated film made of scenes.

The person asks for "a 30-second film about our quarter" and gets a title
card, a number that counts up, bars that grow, a closing card. The model
writes only the scenes (which type, which words, which numbers); how they
move is decided here, so every film has the same calm choreography and no
model ever writes animation code.

Why ONE timeline in script instead of CSS animations: a film has to be
paused, scrubbed, restarted and opened as a still (``?t=6.5``) at exactly the
same frame every time. So every animated element carries a start offset and a
length inside its scene (``data-s`` / ``data-d``), and the page script sets
one number on it per frame, its progress ``--p`` between 0 and 1, from the
current time alone. The stylesheet says what that number means for the
element (rise, draw, grow, light up). A frame is a pure function of time;
nothing depends on what was drawn before. CSS animations could not do this,
and the shared theme switches them off under reduced motion anyway.

The film is laid out at a fixed logical size per format (1280 x 720 for
wide) and scaled to the window with one transform, so type stays crisp and a
line breaks at the same word on every screen. The stage carries its own
theme (a dark film stays dark in the light app); the tokens come from the
shared stylesheet's two scopes, the controls and the backdrop follow the app.

No spec value is ever interpolated raw: texts pass through ``shell.esc`` /
``shell.attr``, numbers are formatted here, and the script reads its timing
from ``data-`` attributes only.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from dodaios.artifacts.design_guide import THEME_CSS
from dodaios.nodes import shell
from dodaios.nodes.shell import attr, esc
from dodaios.nodes.types import NodeError

#: The logical size a film of each format is laid out at, and the factor its
#: type and spacing shrink by (a tall film is narrow, so everything is smaller).
FORMATS: Final[dict[str, tuple[int, int, float, int]]] = {
    "wide": (1280, 720, 1.0, 104),
    "square": (1000, 1000, 0.86, 80),
    "tall": (720, 1280, 0.74, 56),
}
THEMES: Final[tuple[str, ...]] = ("dark", "light")
SCENE_TYPES: Final[tuple[str, ...]] = (
    "title",
    "text",
    "bullets",
    "stat",
    "bars",
    "quote",
    "steps",
    "image",
    "end",
)
TRANSITIONS: Final[tuple[str, ...]] = ("fade", "slide", "zoom", "cut")

MAX_SCENES: Final[int] = 40
MIN_SECONDS: Final[float] = 1.5
MAX_SECONDS: Final[float] = 20.0
MAX_BULLETS: Final[int] = 5
MAX_ITEMS: Final[int] = 8
MAX_STEPS: Final[int] = 5

#: The fields each scene type keeps; everything else in a scene is dropped.
_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "title": ("kicker", "title", "text"),
    "text": ("kicker", "text"),
    "bullets": ("kicker", "title", "bullets"),
    "stat": ("kicker", "value", "unit", "label", "detail"),
    "bars": ("kicker", "title", "items", "unit"),
    "quote": ("quote", "by"),
    "steps": ("kicker", "title", "steps"),
    "image": ("image", "caption"),
    "end": ("kicker", "title", "text"),
}

#: What a scene type cannot do without, and how to say so to the model.
_NEEDS: Final[dict[str, tuple[tuple[str, ...], str]]] = {
    "title": (("title",), "a 'title'"),
    "text": (("text",), "a 'text'"),
    "bullets": (("bullets",), "'bullets': a list of 1 to 5 short points"),
    "stat": (("value",), "a 'value' such as 42 or \"38 %\""),
    "bars": (("items",), '\'items\': 1 to 8 objects {"label", "value": number}'),
    "quote": (("quote",), "a 'quote'"),
    "steps": (("steps",), '\'steps\': 1 to 5 objects {"title", "text"}'),
    "image": (
        ("image",),
        "an 'image' as a data:image/png|jpeg|webp;base64 URI of at most "
        f"{shell.MAX_IMAGE_CHARS} characters",
    ),
    "end": (("title",), "a 'title'"),
}

#: Which field decides the type of a scene that names none, first match wins.
_INFER: Final[tuple[tuple[str, str], ...]] = (
    ("image", "image"),
    ("items", "bars"),
    ("steps", "steps"),
    ("bullets", "bullets"),
    ("quote", "quote"),
    ("value", "stat"),
    ("title", "title"),
    ("text", "text"),
)

_SPEC_HINT: Final[str] = (
    "A motion spec is an object with 'scenes': a list of 1 to 40 scenes, each with a "
    "'type' (" + ", ".join(SCENE_TYPES) + ") and that type's texts."
)


# --- normalize -----------------------------------------------------------------


def _accent(value: Any) -> str:
    """The accent as the spec keeps it: a color name, a hex/rgb/hsl, or nothing."""
    text = " ".join(str(value or "").split())
    if text.lower() in shell.NAMED_COLORS:
        return text.lower()
    if text.startswith("#") and len(text) not in (4, 5, 7, 9):
        return ""
    return text if shell.color(text) else ""


def _value(value: Any) -> str:
    """A stat's value as text: a JSON number is written plainly, text is kept."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        number = shell.number(value)
        return "" if number is None else _plain(number)
    return shell.clean(value, 24)


def _plain(number: float) -> str:
    """A number without noise: 42, 3.5, 0.25 (at most four decimals)."""
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in shell.as_list(value, 64):
        if not isinstance(raw, dict):
            continue
        number = shell.number(raw.get("value"))
        if number is None:
            continue
        number = max(-1e12, min(1e12, round(number, 4)))
        items.append(
            {
                "label": shell.clean(raw.get("label"), 40),
                "value": int(number) if number == int(number) else number,
            }
        )
    return items[:MAX_ITEMS]


def _steps(value: Any) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for raw in shell.as_list(value, 64):
        if isinstance(raw, dict):
            step = {
                "title": shell.clean(raw.get("title"), 60),
                "text": shell.clean(raw.get("text"), 140),
            }
        else:
            step = {"title": shell.clean(raw, 60), "text": ""}
        if step["title"] or step["text"]:
            steps.append(step)
    return steps[:MAX_STEPS]


def _default_seconds(scene: dict[str, Any]) -> float:
    """How long a scene runs when the spec does not say: its entrance plus a hold."""
    kind = scene["type"]
    if kind == "bullets":
        return min(6.0, 3.0 + 0.6 * len(scene["bullets"]))
    if kind == "bars":
        return min(6.0, 3.4 + 0.3 * len(scene["items"]))
    if kind == "steps":
        return min(6.5, 3.0 + 0.8 * len(scene["steps"]))
    if kind == "text":
        return min(7.0, 3.0 + len(scene["text"]) / 45)
    if kind == "quote":
        return min(8.0, 3.5 + len(scene["quote"]) / 45)
    if kind == "image":
        return 5.0
    return 4.0


def _scene(raw: Any, index: int) -> dict[str, Any]:
    """One scene, cleaned: its type, the fields that type uses, its length."""
    where = f"Scene {index + 1}"
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        raise NodeError(f"{where} must be an object with a 'type' and that type's texts.")
    found: dict[str, Any] = {
        "kicker": shell.clean(raw.get("kicker"), 60),
        "title": shell.clean(raw.get("title"), 120),
        "text": shell.clean(raw.get("text"), 280),
        "bullets": [
            text
            for text in (shell.clean(b, 120) for b in shell.as_list(raw.get("bullets"), 64))
            if text
        ][:MAX_BULLETS],
        "value": _value(raw.get("value")),
        "unit": shell.clean(raw.get("unit"), 12),
        "label": shell.clean(raw.get("label"), 80),
        "detail": shell.clean(raw.get("detail"), 140),
        "items": _items(raw.get("items")),
        "quote": shell.clean(raw.get("quote"), 320),
        "by": shell.clean(raw.get("by"), 80),
        "steps": _steps(raw.get("steps")),
        "image": shell.safe_image(raw.get("image")),
        "caption": shell.clean(raw.get("caption"), 140),
    }
    kind = shell.pick(raw.get("type"), SCENE_TYPES, "")
    if not kind:
        kind = next((name for field, name in _INFER if found[field]), "")
    if not kind:
        raise NodeError(
            f"{where} has nothing to show: give it a 'type' ("
            + ", ".join(SCENE_TYPES)
            + ") and that type's texts."
        )
    # A card whose only words arrived in the other text field still has its line.
    if kind in ("title", "end") and not found["title"]:
        found["title"], found["text"] = found["text"][:120], ""
    if kind == "text" and not found["text"]:
        found["text"] = found["title"]
    needed, hint = _NEEDS[kind]
    if not all(found[field] for field in needed):
        raise NodeError(f"{where} ('{kind}') needs {hint}.")
    scene: dict[str, Any] = {"type": kind}
    scene.update({field: found[field] for field in _FIELDS[kind] if found[field]})
    seconds = shell.bounded(raw.get("seconds"), MIN_SECONDS, MAX_SECONDS, _default_seconds(scene))
    scene["seconds"] = round(seconds, 1)
    scene["transition"] = shell.pick(raw.get("transition"), TRANSITIONS, "fade")
    return scene


def normalize(spec: Any) -> dict[str, Any]:
    """A clean film spec. Raises ``NodeError`` with one sentence for the model."""
    if isinstance(spec, list):
        spec = {"scenes": spec}
    if not isinstance(spec, dict):
        raise NodeError(_SPEC_HINT)
    raw_scenes = spec.get("scenes")
    if not isinstance(raw_scenes, (list, tuple)) or not raw_scenes:
        raise NodeError(_SPEC_HINT)
    loop = spec.get("loop")
    return {
        "format": shell.pick(spec.get("format"), tuple(FORMATS), "wide"),
        "theme": shell.pick(spec.get("theme"), THEMES, "dark"),
        "accent": _accent(spec.get("accent")),
        "loop": loop is True or str(loop).strip().lower() == "true",
        "scenes": [_scene(raw, index) for index, raw in enumerate(raw_scenes[:MAX_SCENES])],
    }


# --- the film's parts ----------------------------------------------------------
#
# Every scene renderer returns the scene's inner markup. An animated element
# gets its motion as a class (what ``--p`` means for it) and its cue as two
# attributes (when it starts inside the scene, how long it takes).


def _cue(kind: str, start: float, length: float, classes: str = "") -> str:
    """The attributes of one animated element."""
    names = f"{classes} a a-{kind}" if classes else f"a a-{kind}"
    return f'class="{names}" data-s="{start:.2f}" data-d="{length:.2f}"'


def _words(text: str, start: float, step: float, length: float = 0.9) -> tuple[str, float]:
    """``text`` as words that rise out of their own line, one after another.

    Returns the markup and the moment the last word starts. A long line keeps
    its whole entrance under a second, so the stagger shrinks with the count.
    """
    parts = text.split()
    gap = min(step, 0.9 / max(1, len(parts)))
    spans = [
        f'<span class="w"><span {_cue("word", start + index * gap, length)}>'
        f"{esc(word)}</span></span>"
        for index, word in enumerate(parts)
    ]
    return " ".join(spans), start + gap * max(0, len(parts) - 1)


def _fit(text: str, sizes: tuple[tuple[int, int], ...], floor: int) -> int:
    """The type size for a text of this length: short lines are set larger."""
    return next((size for limit, size in sizes if len(text) <= limit), floor)


def _kicker(scene: dict[str, Any], at: float) -> tuple[str, float]:
    """The small line above a scene's heading, and when the heading may follow."""
    text = scene.get("kicker", "")
    if not text:
        return "", at
    return f"<p {_cue('rise', at, 0.7, 'f-kicker')}>{esc(text)}</p>", at + 0.12


def _head(scene: dict[str, Any], at: float) -> tuple[str, float]:
    """Kicker and heading of a scene that shows something under them."""
    html, at = _kicker(scene, at)
    title = scene.get("title", "")
    if not title:
        return html, at
    size = _fit(title, ((28, 60), (56, 50)), 40)
    html += f'<h2 {_cue("rise", at, 0.8, "f-head")} style="--fs:{size}">{esc(title)}</h2>'
    return html, at + 0.3


def _title_scene(scene: dict[str, Any], at: float, *, closing: bool) -> str:
    html, at = _kicker(scene, at)
    title = scene["title"]
    if closing:
        size = _fit(title, ((24, 96), (48, 76), (84, 60)), 50)
        html = f"<div {_cue('draw', at, 0.7, 'f-rule')}></div>" + html
        at += 0.1
    else:
        size = _fit(title, ((18, 120), (32, 104), (56, 84), (84, 68)), 56)
    words, last = _words(title, at, 0.08)
    html += f'<h2 class="f-title" style="--fs:{size}">{words}</h2>'
    if scene.get("text"):
        html += f"<p {_cue('rise', last + 0.28, 0.8, 'f-text')}>{esc(scene['text'])}</p>"
    return html


def _text_scene(scene: dict[str, Any], at: float) -> str:
    html, at = _kicker(scene, at)
    text = scene["text"]
    size = _fit(text, ((50, 84), (90, 72), (150, 58), (220, 48)), 40)
    # Every word starts at the same cue; the script reads which line each word
    # landed on and delays the lines one after another (``data-lines``).
    words, _ = _words(text, at, 0.0)
    return html + f'<p class="f-say" data-lines="0.16" style="--fs:{size}">{words}</p>'


def _points_size(points: list[str], room: tuple[float, float], head: bool) -> int:
    """The largest type size at which the points still fit under their heading.

    An estimate from the character counts (an average letter is half an em
    wide): good enough to keep five long points on the stage, and short
    points large.
    """
    width, height = room
    for size in (46, 40, 34, 29) if len(points) <= 3 else (40, 34, 29):
        per_line = max(8, int((width - 1.15 * size) / (size * 0.5)))
        lines = sum(-(-len(point) // per_line) for point in points)
        used = lines * size * 1.25 + (len(points) - 1) * 26 + (120 if head else 0)
        if used <= height:
            return size
    return 25


def _bullets_scene(scene: dict[str, Any], at: float, room: tuple[float, float]) -> str:
    html, at = _head(scene, at)
    points = scene["bullets"]
    size = _points_size(points, room, bool(html))
    # The points arrive far enough apart to be read, as far as the scene allows.
    gap = max(0.22, min(0.7, (scene["seconds"] - at - 2.0) / len(points)))
    rows = "".join(
        f"<li {_cue('rise', at + index * gap, 0.7)}>{esc(point)}</li>"
        for index, point in enumerate(points)
    )
    return html + f'<ul class="f-points" style="--fs:{size}">{rows}</ul>'


#: A number as people write it: digits with group and decimal marks between them.
_NUMBER_RE: Final = re.compile("\\d[\\d.,'\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE} ]*\\d|\\d")


def _counted(value: str) -> tuple[str, str, str, float, int, str, str] | None:
    """A stat's value split for counting up, or ``None`` when it is not one number.

    Returns ``(before, number, after, target, decimals, group mark, decimal
    mark)``. The marks are read from the text itself ("1,240.5" or "1.240,5"),
    so the count is written the way the value is; the last frame shows the
    value exactly as it was given.
    """
    match = _NUMBER_RE.search(value)
    if match is None:
        return None
    before, token, after = value[: match.start()], match.group(0), value[match.end() :]
    if any(char.isdigit() for char in before + after):
        return None  # "24/7", "3 of 5": more than one number, nothing to count to
    marks = [char for char in token if not char.isdigit()]
    group = point = ""
    kinds = set(marks)
    if len(kinds) > 2:
        return None
    if len(kinds) == 2:
        point = marks[-1]
        if marks.count(point) != 1 or point not in ".,":
            return None
        group = next(iter(kinds - {point}))
    elif kinds:
        mark = marks[0]
        head, _, tail = token.rpartition(mark)
        thousands = len(tail) == 3 and head.strip("0") != "" and len(head) <= 3
        if len(marks) > 1 or mark not in ".," or thousands:
            group = mark
        else:
            point = mark
    whole, _, fraction = token.partition(point) if point else (token, "", "")
    chunks = whole.split(group) if group else [whole]
    if group and (not 1 <= len(chunks[0]) <= 3 or any(len(chunk) != 3 for chunk in chunks[1:])):
        return None
    digits = "".join(chunks)
    if not digits.isdigit() or (fraction and not fraction.isdigit()) or len(digits) > 12:
        return None
    target = float(f"{digits}.{fraction or '0'}")
    return before, token, after, target, min(len(fraction), 4), group, point or "."


#: A bare number as a program writes it ("99.9"): no group marks, a point.
_BARE_NUMBER_RE: Final = re.compile(r"^-?\d+\.\d+$")
#: Languages that write the decimal mark as a comma.
_COMMA_DECIMAL: Final = frozenset({"de", "es", "pt", "fr", "it", "nl"})


def _localized(value: str, language: str) -> str:
    """A bare decimal number in the reader's writing: ``99.9`` is ``99,9`` in German.

    Only the bare form is touched; a value the model wrote out with its own
    marks or words ("1,240", "38 %") is shown exactly as given.
    """
    if language[:2].lower() in _COMMA_DECIMAL and _BARE_NUMBER_RE.match(value):
        return value.replace(".", ",")
    return value


def _stat_scene(scene: dict[str, Any], at: float, language: str = "en") -> str:
    html, at = _kicker(scene, at)
    value, unit = _localized(scene["value"], language), scene.get("unit", "")
    size = _fit(value + unit, ((4, 248), (6, 208), (9, 160), (13, 120)), 88)
    counted = _counted(value)
    if counted is None:
        figure = esc(value)
    else:
        before, token, after, target, decimals, group, point = counted
        figure = (
            f'{esc(before)}<span {_cue("count", at, 1.5)} data-e="cub" '
            f'data-to="{target:.4f}" data-dec="{decimals}" data-g="{attr(group)}" '
            f'data-pt="{attr(point)}">{esc(token)}</span>{esc(after)}'
        )
    if unit:
        figure += f'<span class="f-unit">{esc(unit)}</span>'
    html += f'<p {_cue("rise", at, 0.9, "f-stat")} style="--fs:{size}">{figure}</p>'
    if scene.get("label"):
        html += f"<p {_cue('rise', at + 0.5, 0.8, 'f-label')}>{esc(scene['label'])}</p>"
    if scene.get("detail"):
        html += f"<p {_cue('rise', at + 0.62, 0.8, 'f-detail')}>{esc(scene['detail'])}</p>"
    return html


def _bars_scene(scene: dict[str, Any], at: float) -> str:
    html, at = _head(scene, at)
    items, unit = scene["items"], scene.get("unit", "")
    top = max(abs(float(item["value"])) for item in items) or 1.0
    size, gap, height = (34, 30, 24) if len(items) <= 4 else (30, 24, 20)
    if len(items) > 6:
        size, gap, height = 25, 16, 15
    # The label column is as wide as the longest label needs, so the bars
    # start close to their names.
    label = min(18, max(len(item["label"]) for item in items) + 1)
    texts = [_plain(float(item["value"])) for item in items]
    # Room for the longest number plus the marks a locale adds, so the column
    # of values does not move while the numbers count up.
    width = max(len(text) for text in texts) + 1 + (len(unit) + 1 if unit else 0)
    suffix = f'<span class="f-unit">{esc(unit)}</span>' if unit else ""
    rows = []
    for index, (item, text) in enumerate(zip(items, texts, strict=True)):
        start = at + index * 0.09
        share = abs(float(item["value"])) / top * 100
        decimals = len(text.partition(".")[2])
        rows.append(
            f"<li {_cue('rise', start, 0.7, 'f-bar')}>"
            f'<span class="f-bar-l">{esc(item["label"])}</span>'
            f'<span class="f-bar-t"><i {_cue("bar", start + 0.1, 1.1)} data-e="cub" '
            f'style="--v:{share:.2f}"></i></span>'
            f'<span class="f-bar-v"><span {_cue("count", start + 0.1, 1.1)} data-e="cub" '
            f'data-to="{float(item["value"]):.4f}" data-dec="{decimals}" data-intl>'
            f"{esc(text)}</span>{suffix}</span></li>"
        )
    return html + (
        f'<ul class="f-bars" style="--fs:{size};--gap:{gap};--bh:{height};--w:{width};'
        f'--lw:{label}">' + "".join(rows) + "</ul>"
    )


def _quote_scene(scene: dict[str, Any], at: float) -> str:
    quote = scene["quote"]
    size = _fit(quote, ((60, 72), (120, 60), (200, 48)), 40)
    parts = quote.split()
    # The quote is revealed word by word, at reading pace but never slower
    # than two seconds for the whole of it.
    gap = max(0.03, min(0.09, 2.0 / len(parts)))
    words = " ".join(
        f"<span {_cue('rise', at + 0.2 + index * gap, 0.6, 'f-word')}>{esc(word)}</span>"
        for index, word in enumerate(parts)
    )
    html = (
        f"<div {_cue('draw', at, 0.7, 'f-rule')}></div>"
        f'<blockquote class="f-quote" style="--fs:{size}">{words}</blockquote>'
    )
    if scene.get("by"):
        after = at + 0.2 + gap * (len(parts) - 1) + 0.45
        html += f"<p {_cue('rise', after, 0.8, 'f-by')}>{esc(scene['by'])}</p>"
    return html


def _steps_scene(scene: dict[str, Any], at: float, *, row: bool) -> str:
    html, at = _head(scene, at)
    steps = scene["steps"]
    count = len(steps)
    # All steps arrive dimmed, then light up one after another over the scene.
    first = at + 0.9
    gap = max(0.35, min(0.9, (scene["seconds"] - first - 1.2) / count))
    size = 36 if count <= 3 else 30 if count == 4 else 25
    if any(len(step["text"]) > 90 or len(step["title"]) > 32 for step in steps):
        size -= 5
    rows = []
    for index, step in enumerate(steps):
        line = ""
        if index < count - 1:
            lit = first + (index + 1) * gap
            line = f'<span class="f-step-line"><i {_cue("draw", lit - 0.3, 0.5)}></i></span>'
        number = index + 1
        text = f"<p>{esc(step['text'])}</p>" if step["text"] else ""
        title = f"<h3>{esc(step['title'])}</h3>" if step["title"] else ""
        rows.append(
            f"<li {_cue('rise', at + index * 0.1, 0.7, 'f-step')}>"
            f"<div {_cue('lit', first + index * gap, 0.6, 'f-step-in')}>"
            f'<div class="f-step-h"><span class="f-step-n"><b>{number}</b>'
            f'<b aria-hidden="true">{number}</b></span>{line}</div>'
            f'<div class="f-step-b">{title}{text}</div></div></li>'
        )
    # Not "row"/"col": the shared kit owns those class names (its column chart).
    layout = "is-row" if row and count > 1 else "is-stack"
    return html + f'<ol class="f-steps {layout}" style="--fs:{size}">' + "".join(rows) + "</ol>"


def _image_scene(scene: dict[str, Any], at: float) -> str:
    caption = scene.get("caption", "")
    # The push-in runs on the scene's own clock, from its first to its last
    # frame, at constant speed: a slow drift, not an entrance.
    picture = (
        f"<div {_cue('fade', at, 0.9, 'f-shot-frame')}>"
        f'<img {_cue("push", 0.0, scene["seconds"])} data-e="lin" '
        f'src="{attr(scene["image"])}" alt="{attr(caption)}"></div>'
    )
    if not caption:
        return f'<figure class="f-shot bleed">{picture}</figure>'
    return (
        f'<figure class="f-shot">{picture}'
        f"<figcaption {_cue('rise', at + 0.5, 0.8, 'f-cap')}>{esc(caption)}</figcaption></figure>"
    )


def _scene_html(
    scene: dict[str, Any], index: int, count: int, film_format: str, language: str = "en"
) -> str:
    kind = scene["type"]
    # The room inside the stage's padding, in the units the type sizes are
    # given in (before the format's factor shrinks them).
    width, height, factor, pad = FORMATS[film_format]
    room = ((width - 2 * pad) / factor, height / factor - 144)
    # Where the scene's own entrances begin: after the scene before it has left.
    at = 0.2 if index == 0 else 0.1 if scene["transition"] == "cut" else 0.34
    if kind in ("title", "end"):
        inner = _title_scene(scene, at, closing=kind == "end")
    elif kind == "text":
        inner = _text_scene(scene, at)
    elif kind == "bullets":
        inner = _bullets_scene(scene, at, room)
    elif kind == "stat":
        inner = _stat_scene(scene, at, language)
    elif kind == "bars":
        inner = _bars_scene(scene, at)
    elif kind == "quote":
        inner = _quote_scene(scene, at)
    elif kind == "steps":
        inner = _steps_scene(scene, at, row=film_format == "wide")
    else:
        inner = _image_scene(scene, at)
    state = " is-on" if index == 0 else ""
    return (
        f'<section class="scene s-{kind}{state}" data-sec="{scene["seconds"]:.1f}" '
        f'data-tr="{scene["transition"]}" aria-label="{index + 1} / {count}">{inner}</section>'
    )


# --- the page ------------------------------------------------------------------


def _tokens(selector: str) -> str:
    """The declarations of one theme scope of the shared stylesheet.

    The stage wears its own theme whatever the app's is, so the film's two
    scopes are cut from the stylesheet every page shares instead of being
    written a second time here.
    """
    start = THEME_CSS.index(selector + "{") + len(selector) + 1
    return THEME_CSS[start : THEME_CSS.index("}", start)]


_TONES_CSS: Final[str] = (
    '.film-fit[data-tone="light"]{'
    + _tokens(":root")
    + '}.film-fit[data-tone="dark"]{'
    + _tokens(':root[data-theme="dark"]')
    + "}"
)

_ICONS: Final[dict[str, str]] = {
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "pause": '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
    "restart": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "loop": (
        '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/>'
        '<path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'
    ),
}


def _icon(name: str) -> str:
    return f'<svg class="i-{name}" viewBox="0 0 24 24" aria-hidden="true">{_ICONS[name]}</svg>'


_FILM_CSS: Final[str] = """
.film{position:fixed;inset:0;display:flex;flex-direction:column;background:var(--bg-2);
  -webkit-user-select:none;user-select:none}
.film-view{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;
  padding:28px 28px 8px}
.film-fit{position:relative;flex:none;overflow:hidden;border-radius:10px;background:var(--bg);
  color:var(--ink);box-shadow:0 0 0 1px var(--line-2);cursor:pointer}
.film.is-idle .film-view,.film.is-idle .film-fit{cursor:none}
.stage{position:absolute;left:0;top:0;overflow:hidden;transform-origin:0 0;background:var(--bg);
  font-family:var(--font);--k:1;--pad:104px}
.scene{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;
  padding:calc(72px*var(--k)) var(--pad);visibility:hidden}
.scene.is-on{visibility:visible}
/* What an element's progress means. --p runs from 0 to 1 and is set by the
   script; left alone it is 1, so a page without script shows settled frames. */
.a{--p:1}
.a-rise{opacity:calc(var(--p)*1.6);
  transform:translate3d(0,calc((1 - var(--p))*var(--y,28px)*var(--k)),0)}
.a-fade{opacity:var(--p)}
.w{display:inline-block;overflow:hidden;vertical-align:top;padding:.1em .06em .2em;
  margin:-.1em -.06em -.2em}
.a-word{display:inline-block;transform:translate3d(0,calc((1 - var(--p))*118%),0)}
.a-draw{transform:scaleX(var(--p));transform-origin:0 50%}
.a-bar{width:calc(var(--p)*var(--v)*1%)}
.a-lit{opacity:calc(.34 + var(--p)*.66)}
.a-push{transform:scale(calc(1 + var(--p)*.06))}
.f-kicker{--y:16px;margin-bottom:calc(20px*var(--k));font-size:calc(28px*var(--k));
  line-height:1.3;font-weight:600;color:var(--fa)}
.f-title{font-size:calc(var(--fs)*var(--k)*1px);line-height:1.04;font-weight:650;
  letter-spacing:-.035em;text-wrap:balance}
.f-text{margin-top:calc(30px*var(--k));max-width:26em;font-size:calc(36px*var(--k));
  line-height:1.35;color:var(--ink-2);text-wrap:pretty}
.f-rule{width:calc(56px*var(--k));height:calc(5px*var(--k));
  margin-bottom:calc(36px*var(--k));border-radius:3px;background:var(--fa)}
.f-say{font-size:calc(var(--fs)*var(--k)*1px);line-height:1.14;font-weight:600;
  letter-spacing:-.028em;text-wrap:balance}
.f-head{margin-bottom:calc(52px*var(--k));font-size:calc(var(--fs)*var(--k)*1px);
  line-height:1.1;font-weight:650;letter-spacing:-.03em;text-wrap:balance}
.f-points{display:grid;gap:calc(26px*var(--k));margin:0;padding:0;list-style:none;
  font-size:calc(var(--fs)*var(--k)*1px);line-height:1.25;font-weight:500;letter-spacing:-.012em}
.f-points li{--y:22px;position:relative;padding-left:1.15em}
.f-points li::before{content:"";position:absolute;left:0;top:.5em;width:.28em;height:.28em;
  border-radius:50%;background:var(--fa)}
.f-stat{--y:36px;margin-left:-.03em;font-size:calc(var(--fs)*var(--k)*1px);line-height:.95;
  font-weight:650;letter-spacing:-.045em;font-variant-numeric:tabular-nums;white-space:nowrap}
.f-unit{margin-left:.22em;color:var(--ink-2);font-weight:600;letter-spacing:-.01em}
.f-stat .f-unit{font-size:.36em}
.f-label{margin-top:calc(32px*var(--k));font-size:calc(42px*var(--k));line-height:1.2;
  font-weight:600;letter-spacing:-.02em}
.f-detail{margin-top:calc(12px*var(--k));max-width:26em;font-size:calc(30px*var(--k));
  line-height:1.35;color:var(--ink-2)}
.f-bars{display:grid;gap:calc(var(--gap)*var(--k)*1px);margin:0;padding:0;list-style:none;
  font-size:calc(var(--fs)*var(--k)*1px);line-height:1.2}
.f-bar{--y:18px;display:grid;column-gap:calc(28px*var(--k));align-items:center;
  grid-template-columns:min(calc(var(--lw)*.58em),34%) minmax(0,1fr) auto}
.f-bar-l{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:var(--ink-2)}
.f-bar-t{display:block;height:calc(var(--bh)*var(--k)*1px)}
.f-bar-t i{display:block;height:100%;min-width:3px;border-radius:0 5px 5px 0;
  background:var(--fa)}
.f-bar-v{min-width:calc(var(--w)*1ch);text-align:right;font-weight:600;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.f-bar-v .f-unit{font-weight:500}
.f-quote{font-size:calc(var(--fs)*var(--k)*1px);line-height:1.22;font-weight:550;
  letter-spacing:-.022em;text-wrap:pretty}
.f-word{--y:10px;display:inline-block}
.f-by{margin-top:calc(40px*var(--k));font-size:calc(30px*var(--k));line-height:1.3;
  color:var(--ink-2)}
.f-steps{display:grid;margin:0;padding:0;list-style:none}
.f-steps.is-row{grid-auto-flow:column;grid-auto-columns:minmax(0,1fr)}
.f-steps.is-stack{row-gap:calc(30px*var(--k))}
.f-step{--y:22px}
.f-steps.is-row .f-step-in{padding-right:calc(28px*var(--k))}
.f-steps.is-stack .f-step-in{display:grid;grid-template-columns:auto minmax(0,1fr);
  column-gap:calc(26px*var(--k));align-items:start}
.f-step-h{display:flex;align-items:center}
.f-steps.is-row .f-step-h{margin-bottom:calc(28px*var(--k))}
.f-step-n{position:relative;flex:none;display:grid;place-items:center;
  width:calc(56px*var(--k));height:calc(56px*var(--k));border-radius:50%;
  box-shadow:inset 0 0 0 1.5px var(--line-2);font-size:calc(24px*var(--k));
  font-variant-numeric:tabular-nums}
.f-step-n::before{content:"";position:absolute;inset:0;border-radius:50%;
  background:var(--fa);opacity:var(--p)}
.f-step-n b{grid-area:1/1;position:relative;font-weight:600;opacity:calc(1 - var(--p))}
.f-step-n b+b{color:var(--fa-ink);opacity:var(--p)}
.f-step-line{flex:1;height:2px;margin:0 calc(-14px*var(--k)) 0 calc(14px*var(--k));
  border-radius:1px;background:var(--line-2)}
.f-step-line i{display:block;height:100%;border-radius:1px;background:var(--fa)}
.f-steps.is-stack .f-step-line{display:none}
.f-step h3{font-size:calc(var(--fs)*var(--k)*1px);line-height:1.2;font-weight:600;
  letter-spacing:-.018em}
.f-steps.is-stack .f-step h3{padding-top:calc(7px*var(--k))}
.f-step p{margin-top:calc(8px*var(--k));font-size:calc(var(--fs)*var(--k)*.76px);
  line-height:1.38;color:var(--ink-2)}
.s-image{padding:0}
.f-shot{position:absolute;inset:0;display:flex;flex-direction:column;gap:calc(22px*var(--k));
  margin:0;padding:calc(56px*var(--k)) var(--pad) calc(40px*var(--k))}
.f-shot-frame{flex:1;min-height:0;overflow:hidden;border-radius:calc(14px*var(--k));
  box-shadow:0 0 0 1px var(--line-2)}
.f-shot img{display:block;width:100%;height:100%;object-fit:cover}
.f-shot.bleed{padding:0}
.f-shot.bleed .f-shot-frame{border-radius:0;box-shadow:none}
.f-cap{flex:none;font-size:calc(28px*var(--k));line-height:1.35;color:var(--ink-2)}
.f-replay{appearance:none;position:absolute;right:14px;bottom:14px;display:grid;
  place-items:center;width:40px;height:40px;border:0;border-radius:50%;
  background:color-mix(in srgb,var(--ink) 12%,var(--bg));color:var(--ink);cursor:pointer}
.f-replay:hover{background:color-mix(in srgb,var(--ink) 20%,var(--bg))}
.film svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
/* The controls: quiet, small, in the app's own theme. */
.film-bar{flex:none;display:flex;align-items:center;gap:4px;width:100%;
  max-width:calc(100% - 32px);margin:0 auto;padding:4px 0 14px;transition:opacity .4s}
.film.is-idle .film-bar:not(:has(:focus-visible)){opacity:0}
.f-btn{appearance:none;flex:none;display:grid;place-items:center;width:32px;height:32px;
  padding:0;border:0;border-radius:8px;background:transparent;color:var(--ink-2);cursor:pointer}
.f-btn:hover{background:var(--bg-3);color:var(--ink)}
.f-btn[aria-pressed="true"]{background:var(--bg-3);color:var(--ink)}
.f-play .i-pause,.film.is-playing .f-play .i-play{display:none}
.film.is-playing .f-play .i-pause{display:block}
.f-scrub{position:relative;flex:1;min-width:48px;height:32px;margin:0 10px;border-radius:6px;
  cursor:pointer;touch-action:none}
.f-track{position:absolute;left:0;right:0;top:50%;height:4px;margin-top:-2px;overflow:hidden;
  border-radius:2px;background:var(--line-2)}
.f-fill{position:absolute;inset:0;transform:scaleX(0);transform-origin:0 50%;
  background:var(--ink)}
.f-tick{position:absolute;top:0;bottom:0;width:3px;margin-left:-1.5px;background:var(--bg-2)}
.f-knob{position:absolute;left:0;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;
  border-radius:50%;background:var(--ink);opacity:0;transition:opacity .15s}
.f-scrub:hover .f-knob,.f-scrub:focus-visible .f-knob,.f-scrub.is-drag .f-knob{opacity:1}
.f-time{flex:none;padding:0 8px 0 2px;font-size:12px;line-height:16px;color:var(--ink-2);
  font-variant-numeric:tabular-nums;white-space:nowrap}
@media (max-width:560px){.film-view{padding:12px 12px 4px}
.film-bar{max-width:calc(100% - 16px);padding:2px 0 10px}.f-scrub{margin:0 6px}}
@media print{.film-bar,.f-replay{display:none!important}}
"""

# The player. One clock (`t`, in seconds), one pure `draw(t)`; everything a
# reader does (play, pause, scrub, step, restart) only moves the clock.
_FILM_JS: Final[str] = """
(function(){
"use strict";
var d=document,root=d.querySelector(".film");if(!root)return;
var view=root.querySelector(".film-view"),fit=root.querySelector(".film-fit"),
  stage=root.querySelector(".stage"),bar=root.querySelector(".film-bar");
var W=+stage.getAttribute("data-w"),H=+stage.getAttribute("data-h");
var each=function(l,f){Array.prototype.forEach.call(l,f);};
var OUT=.36,IN_AT=.14,IN=.62;
function numbers(dec){
  var o={minimumFractionDigits:dec,maximumFractionDigits:dec};
  try{return new Intl.NumberFormat(d.documentElement.lang||undefined,o);}catch(e){}
  try{return new Intl.NumberFormat(undefined,o);}catch(e){}
  return null;}
var scenes=[],total=0;
each(stage.querySelectorAll(".scene"),function(el){
  var sec=+el.getAttribute("data-sec")||4,items=[],end=0;
  each(el.querySelectorAll("[data-lines]"),function(box){
    var top=null,line=-1,gap=+box.getAttribute("data-lines")||.14;
    each(box.querySelectorAll(".w"),function(w){
      if(top===null||Math.abs(w.offsetTop-top)>2){top=w.offsetTop;line++;}
      var a=w.firstElementChild;
      if(a)a.setAttribute("data-s",String((+a.getAttribute("data-s")||0)+line*gap));});});
  each(el.querySelectorAll(".a"),function(a){
    var it={el:a,s:+a.getAttribute("data-s")||0,d:+a.getAttribute("data-d")||.6,
      e:a.getAttribute("data-e")||"",p:-1,c:null};
    if(a.hasAttribute("data-to")){
      var c={to:+a.getAttribute("data-to")||0,dec:+a.getAttribute("data-dec")||0,
        g:a.getAttribute("data-g")||"",pt:a.getAttribute("data-pt")||".",f:null,
        last:a.textContent};
      if(a.hasAttribute("data-intl")){c.f=numbers(c.dec);if(c.f)c.last=c.f.format(c.to);}
      it.c=c;}
    if(it.e!=="lin")end=Math.max(end,it.s+it.d);
    items.push(it);});
  var k=end>sec-.3?Math.max(.15,(sec-.3)/end):1;
  if(k<1)items.forEach(function(it){if(it.e!=="lin"){it.s*=k;it.d*=k;}});
  scenes.push({el:el,at:total,sec:sec,tr:el.getAttribute("data-tr")||"fade",items:items,
    on:null});
  total+=sec;});
if(!scenes.length)return;
var N=scenes.length;
function clamp(x){return x<0?0:x>1?1:x;}
function ease(x,e){x=clamp(x);if(e==="lin")return x;var q=1-x;
  return e==="cub"?1-q*q*q:1-q*q*q*q;}
function counted(c,p){
  if(p>=1)return c.last;
  var n=c.to*p;if(c.f)return c.f.format(n);
  var s=n.toFixed(c.dec).split("."),a=s[0];
  if(c.g)a=a.replace(/\\B(?=(\\d{3})+(?!\\d))/g,c.g);
  return s.length>1?a+c.pt+s[1]:a;}
function put(it,p){
  if(it.p===p)return;it.p=p;it.el.style.setProperty("--p",p.toFixed(4));
  if(it.c)it.el.textContent=counted(it.c,p);}
function pose(el,tr,v,dir){
  var tf="";
  if(tr==="slide")tf="translate3d("+((1-v)*dir*56).toFixed(2)+"px,0,0)";
  else if(tr==="zoom")tf="scale("+(1-(1-v)*dir*.04).toFixed(4)+")";
  el.style.opacity=v.toFixed(4);el.style.transform=tf;}
function index(t){var i=0;for(var n=1;n<N;n++){if(scenes[n].at<=t)i=n;}return i;}
function draw(t){
  var i=index(t),cur=scenes[i],lt=Math.min(t-cur.at,cur.sec),cut=cur.tr==="cut";
  var out=cut||!i?1:clamp(lt/OUT);
  scenes.forEach(function(s,n){
    var on=n===i||(n===i-1&&out<1);
    if(s.on!==on){s.on=on;s.el.classList.toggle("is-on",on);}
    if(!on)return;
    if(n===i){
      pose(s.el,s.tr,cut?1:ease((lt-(i?IN_AT:0))/IN,""),1);
      s.items.forEach(function(it){put(it,ease((lt-it.s)/it.d,it.e));});
    }else{
      pose(s.el,cur.tr,1-out*out,-1);
      s.items.forEach(function(it){put(it,1);});
    }});}
var t=0,playing=false,raf=0,last=0,idle=0,loop=root.getAttribute("data-loop")==="1";
var playB=bar.querySelector(".f-play"),restartB=bar.querySelector(".f-restart"),
  loopB=bar.querySelector(".f-loop"),scrub=bar.querySelector(".f-scrub"),
  fill=bar.querySelector(".f-fill"),knob=bar.querySelector(".f-knob"),
  time=bar.querySelector(".f-time"),replay=fit.querySelector(".f-replay");
function clock(x){x=Math.max(0,Math.floor(x+1e-6));var s=x%60;
  return Math.floor(x/60)+":"+(s<10?"0":"")+s;}
function sync(){
  var f=total?t/total:0,text=clock(t)+" / "+clock(total);
  root.classList.toggle("is-playing",playing);
  playB.setAttribute("aria-label",playing?"Pause":"Play");
  loopB.setAttribute("aria-pressed",loop?"true":"false");
  replay.hidden=playing||t<total;
  fill.style.transform="scaleX("+f.toFixed(5)+")";knob.style.left=(f*100).toFixed(3)+"%";
  time.textContent=text;
  scrub.setAttribute("aria-valuenow",t.toFixed(1));scrub.setAttribute("aria-valuetext",text);}
function wake(){
  root.classList.remove("is-idle");clearTimeout(idle);
  if(playing)idle=setTimeout(function(){if(playing)root.classList.add("is-idle");},2400);}
function frame(now){
  raf=0;if(!playing)return;
  t+=Math.max(0,Math.min(.1,(now-last)/1000));last=now;
  if(t>=total){if(loop){t=t%total;}else{t=total;playing=false;}}
  draw(t);sync();
  if(playing)raf=requestAnimationFrame(frame);else wake();}
function play(){
  if(playing)return;if(t>=total)t=0;
  playing=true;last=performance.now();draw(t);sync();wake();raf=requestAnimationFrame(frame);}
function pause(){
  if(!playing)return;playing=false;if(raf){cancelAnimationFrame(raf);raf=0;}sync();wake();}
function toggle(){if(playing)pause();else play();}
function seek(x){t=Math.max(0,Math.min(total,x));last=performance.now();draw(t);sync();}
function settled(i){return i>=N-1?total:scenes[i].at+scenes[i].sec-.001;}
function step(dir){
  var i=index(t);
  if(playing){
    if(dir>0)seek(i<N-1?scenes[i+1].at:total);
    else seek(i>0&&t-scenes[i].at<.8?scenes[i-1].at:scenes[i].at);
    return;}
  if(dir>0)seek(t<settled(i)-.01?settled(i):settled(Math.min(i+1,N-1)));
  else seek(settled(Math.max(i-1,0)));}
playB.addEventListener("click",toggle);
restartB.addEventListener("click",function(){seek(0);play();});
replay.addEventListener("click",function(){seek(0);play();});
loopB.addEventListener("click",function(){loop=!loop;sync();});
fit.addEventListener("click",function(e){
  if(e.target.closest&&e.target.closest("button"))return;toggle();});
var drag=false,resume=false;
function where(e){var r=scrub.getBoundingClientRect();
  return r.width?clamp((e.clientX-r.left)/r.width)*total:0;}
scrub.addEventListener("pointerdown",function(e){
  drag=true;resume=playing;pause();scrub.classList.add("is-drag");
  try{scrub.setPointerCapture(e.pointerId);}catch(x){}
  seek(where(e));e.preventDefault();scrub.focus();});
scrub.addEventListener("pointermove",function(e){if(drag)seek(where(e));});
function drop(){
  if(!drag)return;drag=false;scrub.classList.remove("is-drag");
  if(resume&&t<total)play();}
scrub.addEventListener("pointerup",drop);scrub.addEventListener("pointercancel",drop);
d.addEventListener("keydown",function(e){
  if(e.altKey||e.ctrlKey||e.metaKey)return;
  var k=e.key;
  if(k===" "||k==="Spacebar"){
    if(e.target&&e.target.closest&&e.target.closest("button"))return;
    e.preventDefault();toggle();}
  else if(k==="ArrowRight"){e.preventDefault();step(1);}
  else if(k==="ArrowLeft"){e.preventDefault();step(-1);}
  else if(k==="Home"){e.preventDefault();seek(0);}
  else if(k==="End"){e.preventDefault();seek(total);}});
["pointermove","pointerdown","keydown","focusin"].forEach(function(n){
  d.addEventListener(n,wake,{passive:true});});
function size(){
  var cs=getComputedStyle(view);
  var w=view.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  var h=view.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom);
  var fw=Math.max(1,Math.floor(W*Math.min(w/W,h/H))),s=fw/W;
  fit.style.width=fw+"px";fit.style.height=Math.round(H*s)+"px";
  stage.style.transform="scale("+s.toFixed(5)+")";bar.style.width=Math.max(fw,300)+"px";}
size();addEventListener("resize",size);
var q=null;try{q=new URLSearchParams(location.search);}catch(e){}
var at=q&&q.get("t")!==null?parseFloat(q.get("t")):NaN;
var still=(q&&q.get("autoplay")==="0")||
  (window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches);
if(!isNaN(at))seek(at);else if(still)seek(settled(0));else{draw(0);sync();play();}
})();
"""


def _ink_on(accent: str) -> str:
    """The text color that reads on the accent (the lit step's number).

    A token accent takes the film's ground, which every series token is
    validated against; a hex from the spec takes near-black or near-white by
    its own luminance.
    """
    match = re.fullmatch(r"#([0-9a-fA-F]{3,8})", accent)
    if match is None:
        return "var(--bg)"
    digits = match.group(1)
    if len(digits) in (3, 4):
        digits = "".join(char * 2 for char in digits[:3])
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#141413" if luminance > 0.36 else "#FDFDFC"


def _total(scenes: list[dict[str, Any]]) -> float:
    return round(sum(float(scene["seconds"]) for scene in scenes), 1)


def render(node: Any) -> str:
    """The film as one self-contained page: the stage, its scenes, the player."""
    spec = normalize(node.spec)
    scenes = spec["scenes"]
    width, height, factor, pad = FORMATS[spec["format"]]
    accent = shell.color(spec["accent"], "var(--accent)")
    total = _total(scenes)
    ticks, elapsed = [], 0.0
    for scene in scenes[:-1]:
        elapsed += float(scene["seconds"])
        ticks.append(f'<i class="f-tick" style="left:{elapsed / total * 100:.3f}%"></i>')
    language = str(getattr(node, "language", "") or "en")
    frames = "".join(
        _scene_html(scene, index, len(scenes), spec["format"], language)
        for index, scene in enumerate(scenes)
    )
    body = (
        f'<div class="film" data-loop="{1 if spec["loop"] else 0}">'
        '<div class="film-view">'
        f'<div class="film-fit" data-tone="{spec["theme"]}" '
        f'style="--fa:{attr(accent)};--fa-ink:{attr(_ink_on(accent))}">'
        f'<div class="stage" data-w="{width}" data-h="{height}" '
        f'style="width:{width}px;height:{height}px;--k:{factor};--pad:{pad}px">{frames}</div>'
        '<button type="button" class="f-replay" aria-label="Replay" hidden>'
        f"{_icon('restart')}</button>"
        "</div></div>"
        '<div class="film-bar" role="group" aria-label="Playback">'
        '<button type="button" class="f-btn f-play" aria-label="Play">'
        f"{_icon('play')}{_icon('pause')}</button>"
        '<button type="button" class="f-btn f-restart" aria-label="Restart">'
        f"{_icon('restart')}</button>"
        '<div class="f-scrub" role="slider" tabindex="0" aria-label="Position" '
        f'aria-valuemin="0" aria-valuemax="{total:.1f}" aria-valuenow="0">'
        f'<div class="f-track"><div class="f-fill"></div>{"".join(ticks)}</div>'
        '<div class="f-knob"></div></div>'
        '<span class="f-time" aria-hidden="true"></span>'
        '<button type="button" class="f-btn f-loop" aria-label="Loop" '
        f'aria-pressed="{"true" if spec["loop"] else "false"}">{_icon("loop")}</button>'
        "</div></div>"
    )
    return shell.document(
        node,
        body=body,
        css=_TONES_CSS + _FILM_CSS,
        js=_FILM_JS,
        body_class="fill",
        kit_js=False,
    )


# --- the library card, the starter, the guide ----------------------------------

#: The fields a card's two lines are read from, most telling first.
_MAIN_FIELDS: Final[tuple[str, ...]] = ("title", "text", "quote", "value", "caption")
_SIDE_FIELDS: Final[tuple[str, ...]] = ("text", "label", "by", "detail", "kicker", "caption")


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on a film's card."""
    scenes = [scene for scene in spec.get("scenes") or [] if isinstance(scene, dict)]
    title = subtitle = ""
    for scene in scenes:
        title = next((str(scene[f]) for f in _MAIN_FIELDS if scene.get(f)), "")
        if title:
            subtitle = next(
                (str(scene[f]) for f in _SIDE_FIELDS if scene.get(f) and str(scene[f]) != title),
                "",
            )
            break
    return {
        "title": title[:60],
        "subtitle": subtitle[:80],
        "seconds": _total(scenes) if scenes else 0.0,
        "dark": spec.get("theme", "dark") != "light",
        "accent": shell.color(spec.get("accent")),
        "format": shell.pick(spec.get("format"), tuple(FORMATS), "wide"),
    }


def starter(title: str, language: str) -> dict[str, Any]:
    """A three-scene film around the node's title.

    ``language`` is accepted for the contract; the few placeholder words are
    English and are replaced with the first real edit.
    """
    name = shell.clean(title, 120) or "Untitled"
    return normalize(
        {
            "scenes": [
                {"type": "title", "title": name},
                {
                    "type": "bullets",
                    "title": "Key points",
                    "bullets": ["First point", "Second point", "Third point"],
                },
                {"type": "end", "title": name},
            ]
        }
    )


EXAMPLE: Final[dict[str, Any]] = {
    "format": "wide",
    "accent": "green",
    "scenes": [
        {
            "type": "title",
            "kicker": "Q3 review",
            "title": "A quarter of steady growth",
            "text": "July to September, all regions.",
        },
        {"type": "stat", "value": "1,240", "label": "new customers", "detail": "up from 910"},
        {
            "type": "bars",
            "title": "Revenue by region",
            "unit": "k",
            "items": [{"label": "North", "value": 420}, {"label": "South", "value": 310}],
        },
        {"type": "end", "title": "Next: the Q4 plan", "transition": "zoom"},
    ],
}

GUIDE: Final[str] = (
    "motion: a short film of scenes on one timeline. You write the scenes; the motion "
    "is built in.\n"
    'Spec: {"format": "wide" (16:9, default) | "square" | "tall" (9:16), "theme": "dark" '
    '(default) | "light", "accent": color, "loop": bool, "scenes": [scene, ...]}\n'
    "- accent: ONE color for the whole film: blue, orange, green, amber, violet, pink, "
    "or a hex.\n"
    '- scenes: 1 to 40, played in order. Each has "type", that type\'s fields, optional '
    '"seconds" (1.5 to 20; by default as long as its content needs) and "transition": '
    "fade (default) | slide | zoom | cut.\n"
    "Scene types and the fields they keep (anything else is dropped):\n"
    "- title: kicker, title, text. The opening; the title's words rise in one by one.\n"
    "- text: kicker, text. One statement set large, revealed line by line.\n"
    "- bullets: kicker, title, bullets (up to 5 short points, arriving one by one).\n"
    '- stat: kicker, value, unit, label, detail. One number that counts up. "value": a '
    "number (99.9 is written the reader's way) or text shown as given "
    '("1,240", "38 %").\n'
    "- bars: kicker, title, items [{label, value: number}] (up to 8), unit. Bars grow to "
    "their values.\n"
    "- quote: quote, by.\n"
    "- steps: kicker, title, steps [{title, text}] (up to 5), lighting up in order.\n"
    "- image: image (a data:image/...;base64 URI), caption. A slow push-in.\n"
    "- end: kicker, title, text. The closing card.\n"
    'Without "type" the fields decide (bullets -> bullets, value -> stat, items -> bars).\n'
    "Writing a film: one thought per scene. 5 to 9 scenes and 20 to 45 seconds are "
    "plenty. Open with a title, close with an end card, vary the types in between. "
    "Keep every text short enough to read in its scene: a title under 40 characters, a "
    "statement under 120, a bullet under 60. Use real numbers with their units; cut any "
    "scene that only repeats another. Give a scene more seconds only when it carries "
    "more to read.\n"
    "Example:\n" + json.dumps(EXAMPLE, ensure_ascii=False, separators=(",", ":"))
)

__all__ = [
    "EXAMPLE",
    "FORMATS",
    "GUIDE",
    "SCENE_TYPES",
    "TRANSITIONS",
    "normalize",
    "preview",
    "render",
    "starter",
]
