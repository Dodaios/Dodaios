"""What a rendered node page offers for editing, read back from its markup.

A renderer marks the texts a reader may write into with ``data-at`` (the place
in the spec) and friends (see :mod:`dodaios.nodes.bridge`). These helpers read
those marks from a page and check them against the spec, so every type's
tests can say "what the page offers to edit is exactly what the spec holds".
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

TITLE_PATH = "@title"
_VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "path", "circle", "rect", "line"})


@dataclass(frozen=True)
class Field:
    """One editable text of a page."""

    at: str
    text: str
    src: str | None
    kind: str
    multiline: bool
    refresh: bool


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[Field] = []
        self._open: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for entry in self._open:
            if tag not in _VOID:
                entry["depth"] += 1
        given = dict(attrs)
        if "data-at" in given and tag not in _VOID:
            self._open.append({"attrs": given, "depth": 1, "text": []})

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        for entry in list(self._open):
            entry["depth"] -= 1
            if entry["depth"] == 0:
                self._open.remove(entry)
                attrs = entry["attrs"]
                self.fields.append(
                    Field(
                        at=str(attrs["data-at"]),
                        text=" ".join("".join(entry["text"]).split()),
                        src=attrs.get("data-src"),
                        kind=str(attrs.get("data-as") or "text"),
                        multiline="data-multiline" in attrs,
                        refresh="data-refresh" in attrs,
                    )
                )

    def handle_data(self, data: str) -> None:
        for entry in self._open:
            entry["text"].append(data)


def editable_fields(page: str) -> list[Field]:
    """Every element of ``page`` that carries ``data-at``, in page order of closing."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    return reader.fields


def resolve(spec: Any, pointer: str) -> Any:
    """The value at a JSON Pointer in ``spec``. Raises ``LookupError`` when there is none."""
    if not pointer.startswith("/"):
        raise LookupError(pointer)
    value = spec
    for part in pointer[1:].split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise LookupError(pointer)
    return value


def _same(shown: str, value: Any, kind: str) -> bool:
    if kind == "toggle":
        return shown == ("true" if value else "false")
    if kind == "number":
        if value is None or value == "":
            return shown == ""
        try:
            return float(shown) == float(value)
        except (TypeError, ValueError):
            return False
    wanted = "" if value is None else str(value)
    return " ".join(shown.split()) == " ".join(wanted.split())


def check_editable(page: str, spec: dict[str, Any], title: str) -> list[Field]:
    """Assert that what ``page`` offers to edit is what ``spec`` holds.

    Every ``data-at`` names a place that exists in the spec (or the node's
    title), and the field's value (``data-src`` when given, else the shown
    text) equals the value there. Returns the fields, for further asserts.
    """
    fields = editable_fields(page)
    for field in fields:
        value = title if field.at == TITLE_PATH else resolve(spec, field.at)
        assert not isinstance(value, (dict, list)), f"{field.at} is not one value"
        shown = field.src if field.src is not None else field.text
        assert _same(shown, value, field.kind), (
            f"{field.at}: the page offers {shown!r}, the spec holds {value!r}"
        )
    return fields
