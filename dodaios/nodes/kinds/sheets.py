"""Sheets: a spreadsheet the assistant writes and the person reads.

A sheet is the general form of the living page's table
(:mod:`dodaios.artifacts.living`): typed columns instead of plain text, so a
number is right-aligned and written the way the reader's locale writes it, a
date reads as a date, a status is a chip and a column can carry a total. The
person sorts, filters and moves through the grid. In the app's edit mode
(:mod:`dodaios.nodes.bridge`) the person may also write into a cell, a column
label, a sheet's name, the note and the title; each change is saved into the
spec, which stays the one source of what the page shows.

Why an edited cell is sometimes followed up in the page and sometimes drawn
again: the reader's place in a grid (the open sheet, the sort, the filter, the
scroll inside the grid) is lost when the page is drawn again. So a plain sheet
writes a saved value into its own grid (the number formatted, the date
written out, the chip and the link kept). A sheet whose values feed a formula
or a total, and a value only Python can read (a status word's tone, whether a
text is an address, a number typed in a notation the page is not sure of, an
emptied cell whose row may go), asks the app to draw the page again.

Why formulas are evaluated HERE and not in the page: the page is a rendering
of the spec, and a value the reader sees must be the value the assistant can
read back. A formula is therefore a small arithmetic expression over the
row's other columns, parsed with :mod:`ast` and walked by an evaluator that
knows numbers, column keys, the arithmetic operators and five functions.
Nothing is ever handed to ``eval``; an expression outside that grammar is
refused when the spec is normalized, with the column named, so the model can
correct it. A formula whose inputs are missing, or that divides by zero,
leaves its cell empty: one bad row must not break a sheet.

Why a column's type may stay unset in the normalized spec: a kept-current
sheet often starts empty and gets its rows later. A type inferred once and
stored would freeze "text" onto a column that turns out to hold numbers, so
the inference runs again on every normalize and every render.

The page ships each number twice: the raw value in ``data-value`` (what the
script sorts, totals and formats with ``Intl.NumberFormat`` in the viewer's
locale) and a fallback text formatted here in the node's language, which is
what a reader sees for the instant before the script runs and in any viewer
without script. No spec value is ever written into the script or the styles;
the script reads the grid it is given.
"""

from __future__ import annotations

import ast
import json
import keyword
import math
import operator
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from dodaios.nodes.shell import (
    as_list,
    attr,
    bounded,
    clean,
    document,
    esc,
    number,
    pick,
    safe_link,
    upkeep_meta,
)
from dodaios.nodes.types import NodeError

MAX_SHEETS: Final[int] = 12
MAX_COLUMNS: Final[int] = 30
MAX_ROWS: Final[int] = 1_000
MAX_FREEZE: Final[int] = 3
MAX_DECIMALS: Final[int] = 4
MAX_CELL_CHARS: Final[int] = 500
MAX_NAME_CHARS: Final[int] = 40
MAX_LABEL_CHARS: Final[int] = 60
MAX_KEY_CHARS: Final[int] = 40
MAX_UNIT_CHARS: Final[int] = 12
MAX_NOTE_CHARS: Final[int] = 200
MAX_STATUS_CHARS: Final[int] = 60
MAX_DATE_CHARS: Final[int] = 40
MAX_FORMULA_CHARS: Final[int] = 200
#: A formula is a line of arithmetic, not a program.
MAX_FORMULA_NODES: Final[int] = 120
#: ``**`` with a larger exponent yields an empty cell instead of a huge number.
MAX_EXPONENT: Final[float] = 64.0
#: Integers a page script can still hold exactly.
_MAX_EXACT: Final[int] = 2**53

COLUMN_TYPES: Final[tuple[str, ...]] = (
    "text",
    "number",
    "currency",
    "percent",
    "date",
    "check",
    "status",
    "link",
)
TOTALS: Final[tuple[str, ...]] = ("sum", "avg", "min", "max", "count")
TONES: Final[tuple[str, ...]] = ("good", "info", "warn", "bad")
_NUMERIC: Final[frozenset[str]] = frozenset({"number", "currency", "percent"})

#: What a model may call a type.
_TYPE_ALIASES: Final[dict[str, str]] = {
    **{name: name for name in COLUMN_TYPES},
    "string": "text",
    "str": "text",
    "int": "number",
    "integer": "number",
    "float": "number",
    "numeric": "number",
    "money": "currency",
    "price": "currency",
    "percentage": "percent",
    "datetime": "date",
    "bool": "check",
    "boolean": "check",
    "checkbox": "check",
    "state": "status",
    "url": "link",
}

#: Status words whose meaning is plain enough to carry a tone by themselves.
#: Everything else is a neutral chip; a spec gives the tone explicitly for
#: other words and other languages.
_STATUS_TONES: Final[dict[str, str]] = {
    **dict.fromkeys(
        (
            "done",
            "paid",
            "delivered",
            "ok",
            "complete",
            "completed",
            "shipped",
            "approved",
            "active",
            "won",
            "passed",
            "resolved",
        ),
        "good",
    ),
    **dict.fromkeys(
        (
            "pending",
            "open",
            "in progress",
            "in transit",
            "in review",
            "waiting",
            "planned",
            "scheduled",
            "sent",
            "new",
            "todo",
        ),
        "info",
    ),
    **dict.fromkeys(("at risk", "delayed", "due soon", "on hold", "paused"), "warn"),
    **dict.fromkeys(
        (
            "late",
            "overdue",
            "blocked",
            "failed",
            "rejected",
            "cancelled",
            "canceled",
            "error",
            "lost",
            "missing",
        ),
        "bad",
    ),
}

_TRUE_WORDS: Final[frozenset[str]] = frozenset({"true", "yes", "y", "x", "1", "on", "done"})
_FALSE_WORDS: Final[frozenset[str]] = frozenset({"false", "no", "n", "0", "off", "-"})

#: Languages that write a decimal comma (the rule of ``report_blocks.format_number``).
_COMMA_DECIMAL: Final[frozenset[str]] = frozenset({"de", "es", "pt", "fr", "it", "nl"})
#: Currency signs a spec may give instead of a code; the page script needs the code.
_CURRENCY_CODES: Final[dict[str, str]] = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
#: Currencies written without minor units.
_ZERO_DECIMAL: Final[frozenset[str]] = frozenset({"JPY", "KRW", "VND", "CLP", "ISK"})

_TOTAL_MARKS: Final[dict[str, str]] = {
    "sum": "Σ",
    "avg": "Ø",
    "min": "min",
    "max": "max",
    "count": "#",
}

_SEND: Final[str] = (
    "Send 'sheets': a list of 1 to 12 sheets, each with 'columns' (labels or column objects) "
    "and 'rows' (objects keyed by column key, or lists of cells in column order)."
)


# ------------------------------------------------------------------- formulas
#
# The grammar is what `_check` accepts and nothing else: finite numbers,
# names, + - * / // % **, unary plus and minus, parentheses, and calls of the
# five functions below with positional arguments.


class _NoValue(Exception):
    """An input of the formula is missing; its cell stays empty."""


def _round(value: float, places: float = 0.0) -> float:
    """Round half away from zero, the way a spreadsheet does (not to even)."""
    digits = int(max(-10.0, min(10.0, places)))
    try:
        step = Decimal(1).scaleb(-digits)
        return float(Decimal(repr(value)).quantize(step, rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:  # more digits than a Decimal context holds
        raise _NoValue from exc


def _power(base: float, exponent: float) -> float:
    if abs(exponent) > MAX_EXPONENT:
        raise _NoValue
    result = base**exponent
    if isinstance(result, complex):  # a root of a negative number
        raise _NoValue
    return float(result)


_BINARY: Final[dict[type[ast.operator], Callable[[float, float], float]]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _power,
}

#: name -> (function, fewest arguments, most arguments)
_FUNCTIONS: Final[dict[str, tuple[Callable[..., float], int, int]]] = {
    "round": (_round, 1, 2),
    "abs": (abs, 1, 1),
    "min": (min, 1, 30),
    "max": (max, 1, 30),
    "sum": (lambda *values: math.fsum(values), 1, 30),
}


def _check(node: ast.AST) -> None:
    """Raise ``ValueError`` when ``node`` is outside the formula grammar."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("constant")
        if not math.isfinite(float(value)):
            raise ValueError("constant")
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _check(node.operand)
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        _check(node.left)
        _check(node.right)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        known = _FUNCTIONS.get(node.func.id)
        if known is None or not known[1] <= len(node.args) <= known[2]:
            raise ValueError("call")
        for argument in node.args:
            _check(argument)
        return
    raise ValueError(type(node).__name__)


def _names(tree: ast.expr) -> list[str]:
    """The column keys a formula reads (function names are not among them)."""
    functions = {
        id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in functions and node.id not in found:
            found.append(node.id)
    return found


def parse_formula(expression: str, column: str = "") -> ast.expr:
    """The expression as a checked syntax tree, or ``NodeError`` naming ``column``."""
    where = f"Column '{column}': the" if column else "The"
    refusal = NodeError(
        f"{where} formula may only use numbers, the keys of the row's other columns, "
        "+ - * / // % **, parentheses and round, min, max, abs, sum."
    )
    text = str(expression or "").strip()
    if not text or len(text) > MAX_FORMULA_CHARS:
        raise refusal
    try:
        tree = ast.parse(text, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_FORMULA_NODES:
            raise ValueError("size")
        _check(tree.body)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise refusal from exc
    return tree.body


def _walk(node: ast.expr, values: Mapping[str, Any]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        value = values.get(node.id)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _NoValue
        return float(value)
    if isinstance(node, ast.UnaryOp):
        operand = _walk(node.operand, values)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        return _BINARY[type(node.op)](_walk(node.left, values), _walk(node.right, values))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS[node.func.id][0]
        return float(function(*(_walk(argument, values) for argument in node.args)))
    raise _NoValue


def evaluate(tree: ast.expr, values: Mapping[str, Any]) -> float | None:
    """The formula's value for one row, or ``None`` for an empty cell.

    ``values`` maps column keys to the row's cells; anything that is not a
    number counts as missing.
    """
    try:
        result = _walk(tree, values)
    except (_NoValue, ArithmeticError, ValueError, KeyError):
        # a missing input, a division by zero or an overflow: the cell stays empty
        return None
    if not math.isfinite(result):
        return None
    result = round(result, 10)
    return 0.0 if result == 0 else result


def evaluate_formula(expression: str, values: Mapping[str, Any]) -> float | None:
    """Parse and evaluate in one step (``NodeError`` for a refused expression)."""
    return evaluate(parse_formula(expression), values)


def _formula_order(columns: list[dict[str, Any]], sheet: str = "") -> list[tuple[str, ast.expr]]:
    """The formula columns in the order they can be computed.

    Raises ``NodeError`` for a formula that names something that is not
    another column of the sheet, or that depends on itself.
    """
    keys = [str(column.get("key") or "") for column in columns]
    trees: dict[str, ast.expr] = {}
    needs: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for column in columns:
        formula = column.get("formula")
        if not formula:
            continue
        key = str(column.get("key") or "")
        label = str(column.get("label") or key)
        labels[key] = label
        trees[key] = parse_formula(str(formula), label)
        needs[key] = _names(trees[key])
        for name in needs[key]:
            if name == key or name not in keys:
                others = ", ".join(k for k in keys if k != key) or "none"
                raise NodeError(
                    f"Column '{label}': the formula names '{clean(name, 40)}', which is not "
                    f"the key of another column in sheet '{sheet}' (keys: {others})."
                )
    order: list[tuple[str, ast.expr]] = []
    state: dict[str, int] = {}

    def visit(key: str) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise NodeError(
                f"Column '{labels[key]}': the formula depends on itself through other "
                "formula columns; compute it from columns that hold values."
            )
        state[key] = 1
        for name in needs[key]:
            if name in trees:
                visit(name)
        state[key] = 2
        order.append((key, trees[key]))

    for key in trees:
        visit(key)
    return order


def _filled(
    rows: list[dict[str, Any]], order: list[tuple[str, ast.expr]]
) -> list[dict[str, Any]]:
    """The rows with their formula cells computed."""
    if not order:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        full = dict(row)
        for key, tree in order:
            value = evaluate(tree, full)
            if value is None:
                full.pop(key, None)
            else:
                full[key] = value
        out.append(full)
    return out


# ---------------------------------------------------------------- normalizing


def _slug(value: Any, index: int) -> str:
    """A column key: lower-case, ``_`` for every character a name cannot hold."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(ch if ("a" + ch).isidentifier() else "_" for ch in text)
    text = re.sub(r"_+", "_", text).strip("_")[:MAX_KEY_CHARS].rstrip("_")
    if not text:
        return f"col{index + 1}"
    if text[0].isdigit():
        text = ("_" + text)[:MAX_KEY_CHARS]
    if keyword.iskeyword(text):
        text += "_"
    return text


def _unique(key: str, used: set[str]) -> str:
    candidate, count = key, 1
    while candidate in used:
        count += 1
        suffix = f"_{count}"
        candidate = key[: MAX_KEY_CHARS - len(suffix)].rstrip("_") + suffix
    used.add(candidate)
    return candidate


def _num(value: Any) -> int | float | None:
    """A finite number from a JSON number or a numeric string, else ``None``."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) <= _MAX_EXACT:
        return value
    try:
        result = number(value)
    except OverflowError:  # an integer too large for a float is not a cell value
        return None
    if result is None or isinstance(value, float):
        return result
    return int(result) if result.is_integer() and abs(result) <= _MAX_EXACT else result


def _text_of(value: Any) -> str:
    """The text a cell of any JSON shape stands for."""
    if isinstance(value, dict):
        value = value.get("text") or value.get("label") or value.get("href") or ""
    if isinstance(value, (list, tuple)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value if value is not None else "")


def _link_cell(value: Any) -> Any:
    if isinstance(value, dict):
        href = safe_link(value.get("href") or value.get("url"))
        text = clean(value.get("text") or value.get("label"), MAX_CELL_CHARS)
        if href:
            return {"text": text or href[:MAX_CELL_CHARS], "href": href}
        return text or None
    text = clean(_text_of(value), MAX_CELL_CHARS)
    href = safe_link(text) if " " not in text else ""
    if href:
        return {"text": href, "href": href}
    return text or None


def _status_cell(value: Any) -> Any:
    text = clean(_text_of(value), MAX_STATUS_CHARS)
    if not text:
        return None
    tone = pick(value.get("tone"), TONES, "") if isinstance(value, dict) else ""
    return {"text": text, "tone": tone} if tone else text


def _free_cell(value: Any) -> Any:
    """A cell of a column without a strict type: its JSON shape is kept."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _num(value)
    if isinstance(value, dict):
        if safe_link(value.get("href") or value.get("url")):
            return _link_cell(value)
        if pick(value.get("tone"), TONES, ""):
            return _status_cell(value)
    return clean(_text_of(value), MAX_CELL_CHARS) or None


def _cell(value: Any, kind: str | None) -> Any:
    """One cell as the column's type holds it, or ``None`` for an empty one."""
    if value is None:
        return None
    if kind in _NUMERIC:
        if isinstance(value, bool):
            return None
        found = _num(value)
        if found is not None or isinstance(value, (int, float)):
            return found  # a number, or one that is not finite and so no value
        # Text in a number column ("n/a") is kept and shown as written.
        return clean(_text_of(value), MAX_CELL_CHARS) or None
    if kind == "check":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        word = clean(_text_of(value), 12).lower()
        return True if word in _TRUE_WORDS else False if word in _FALSE_WORDS else None
    if kind == "status":
        return _status_cell(value)
    if kind == "link":
        return _link_cell(value)
    if kind == "date":
        return clean(_text_of(value), MAX_DATE_CHARS) or None
    return _free_cell(value)


def _columns(
    raw_columns: Any, raw_rows: list[Any], sheet: str
) -> tuple[list[dict[str, Any]], list[tuple[str, ...]]]:
    """The sheet's columns, and for each the names a row may use for it."""
    given = as_list(raw_columns, MAX_COLUMNS)
    if not given:
        # No columns sent: the keys the rows use are the columns, as on a living page.
        seen: list[Any] = []
        for row in raw_rows:
            for name in row if isinstance(row, dict) else ():
                if clean(name, MAX_LABEL_CHARS) and name not in seen:
                    seen.append(name)
        given = seen[:MAX_COLUMNS]
    columns: list[dict[str, Any]] = []
    other_names: list[tuple[str, str]] = []
    used: set[str] = set()
    for raw in given:
        if not isinstance(raw, dict):
            raw = {"label": raw} if isinstance(raw, (str, int, float)) else {}
        label = clean(raw.get("label") or raw.get("name") or raw.get("title"), MAX_LABEL_CHARS)
        raw_key = clean(raw.get("key") or raw.get("id"), 80)
        if not label and not raw_key:
            continue
        key = _unique(_slug(raw_key or label, len(columns)), used)
        label = label or raw_key[:MAX_LABEL_CHARS]
        column: dict[str, Any] = {"key": key, "label": label}
        kind = _TYPE_ALIASES.get(str(raw.get("type") or "").strip().lower())
        formula = " ".join(str(raw.get("formula") or "").split()).lstrip("=").strip().lower()
        if formula:
            # Checked here for its grammar, and against the other keys once all are known.
            parse_formula(formula, label)
            if kind not in _NUMERIC:
                kind = None
        if kind:
            column["type"] = kind
        unit = clean(raw.get("unit"), MAX_UNIT_CHARS)
        if unit:
            column["unit"] = unit
        if number(raw.get("decimals")) is not None:
            column["decimals"] = int(bounded(raw.get("decimals"), 0, MAX_DECIMALS, 0))
        total = pick(raw.get("total"), TOTALS, "")
        if total:
            column["total"] = total
        if formula:
            column["formula"] = formula
        columns.append(column)
        other_names.append((raw_key.lower(), label.lower()))
    if not columns:
        raise NodeError(
            f"Sheet '{sheet}' needs 'columns': 1 to 30 labels or column objects "
            "(or rows as objects, whose keys become the columns)."
        )
    # A row may also name a column by the key as it was sent or by its label,
    # unless that name is another column's key or an earlier column's name:
    # two columns with the same label must not read the same cell.
    aliases: list[tuple[str, ...]] = []
    taken: set[str] = set(used)
    for column, names in zip(columns, other_names, strict=True):
        own = [column["key"]]
        for name in names:
            if name and name not in taken:
                taken.add(name)
                own.append(name)
        aliases.append(tuple(own))
    return columns, aliases


def _rows(
    raw_rows: list[Any], columns: list[dict[str, Any]], aliases: list[tuple[str, ...]]
) -> list[dict[str, Any]]:
    """Rows as objects keyed by column key. A row without any cell is dropped."""
    out: list[dict[str, Any]] = []
    for raw in raw_rows[:MAX_ROWS]:
        if isinstance(raw, dict):
            lowered = {clean(name, 80).lower(): value for name, value in raw.items()}
            cells = [
                next((lowered[name] for name in names if name in lowered), None)
                for names in aliases
            ]
        elif isinstance(raw, (list, tuple)):
            cells = list(raw[: len(columns)])
        else:
            continue
        row: dict[str, Any] = {}
        for column, value in zip(columns, cells, strict=False):
            if "formula" in column:
                continue
            cell = _cell(value, column.get("type"))
            if cell is not None:
                row[column["key"]] = cell
        if row:
            out.append(row)
    return out


def _sheet(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise NodeError(f"Sheet {index + 1} must be an object with 'columns' and 'rows'.")
    name = clean(raw.get("name") or raw.get("title"), MAX_NAME_CHARS) or f"Sheet {index + 1}"
    raw_rows = raw.get("rows")
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, (list, tuple)):
        raise NodeError(
            f"Sheet '{name}': 'rows' must be a list of objects keyed by column key, "
            "or of lists of cells in column order."
        )
    columns, aliases = _columns(raw.get("columns"), list(raw_rows), name)
    _formula_order(columns, name)
    return {
        "name": name,
        "columns": columns,
        "rows": _rows(list(raw_rows), columns, aliases),
        "freeze": int(bounded(raw.get("freeze"), 0, MAX_FREEZE, 1)),
    }


def normalize(spec: Any) -> dict[str, Any]:
    """The spec as the renderer accepts it. Raises ``NodeError``. Idempotent."""
    if not isinstance(spec, dict):
        raise NodeError(_SEND)
    raw_sheets = spec.get("sheets")
    if isinstance(raw_sheets, dict):
        raw_sheets = [raw_sheets]
    if not isinstance(raw_sheets, (list, tuple)) or not raw_sheets:
        if not (spec.get("columns") or spec.get("rows")):
            raise NodeError(_SEND)
        raw_sheets = [spec]  # the shorthand: the spec itself is the one sheet
    out: dict[str, Any] = {
        "sheets": [_sheet(raw, index) for index, raw in enumerate(raw_sheets[:MAX_SHEETS])]
    }
    note = clean(spec.get("note"), MAX_NOTE_CHARS)
    if note:
        out["note"] = note
    return out


# ------------------------------------------------------------- reading a sheet


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _kind(column: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """The column's type: the given one, else what its cells are."""
    given = column.get("type")
    if column.get("formula"):
        return given if given in _NUMERIC else "number"
    if given in COLUMN_TYPES:
        return str(given)
    key = column.get("key")
    cells = [row[key] for row in rows if key in row]
    if cells and all(_is_number(cell) for cell in cells):
        return "number"
    if cells and all(isinstance(cell, bool) for cell in cells):
        return "check"
    return "text"


def _needed_decimals(value: float, cap: int = 2) -> int:
    text = f"{abs(value):.{cap}f}".rstrip("0")
    return len(text) - text.index(".") - 1


def _decimals(column: dict[str, Any], kind: str, values: list[float]) -> int:
    """How many decimals the whole column shows, so its numbers line up."""
    given = column.get("decimals")
    if _is_number(given):
        return int(bounded(given, 0, MAX_DECIMALS, 0))
    if kind == "currency":
        code = _currency_code(str(column.get("unit") or ""))
        return 0 if code in _ZERO_DECIMAL else 2
    return max((_needed_decimals(value) for value in values), default=0)


def _currency_code(unit: str) -> str:
    return _CURRENCY_CODES.get(unit, unit.upper())


def _raw(value: float) -> str:
    """A number as the page script reads it back."""
    as_float = float(value)
    if as_float.is_integer() and abs(as_float) < 1e15:
        return str(int(as_float))
    return repr(as_float)


def _comma(language: str) -> bool:
    return (language or "").strip().lower()[:2] in _COMMA_DECIMAL


def _format(value: float, decimals: int, language: str) -> str:
    """A number as the node's language writes it: ``1.234,50`` or ``1,234.50``."""
    text = f"{value:,.{decimals}f}"
    if text.startswith("-") and not text.strip("-0.,"):
        text = text[1:]
    if _comma(language):
        text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return text.replace("-", "−")


def _iso(value: Any) -> str:
    """``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM`` when the text is an ISO date, else empty."""
    text = str(value or "").strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        if 16 <= len(text) <= 32 and text[10] in "T ":
            return datetime.fromisoformat(text.replace(" ", "T", 1)).strftime("%Y-%m-%dT%H:%M")
    except ValueError:  # not a date the page can format: it is shown as written
        return ""
    return ""


def _status_tone(value: Any) -> tuple[str, str]:
    """A status cell's text and tone ("" for a neutral chip)."""
    if isinstance(value, dict):
        return str(value.get("text") or ""), pick(value.get("tone"), TONES, "")
    text = _text_of(value)
    return text, _STATUS_TONES.get(text.strip().lower().rstrip(".!"), "")


def _link_label(text: str, href: str) -> str:
    """What a link shows: its text, or the address without the scheme."""
    if text and text != href:
        return text
    return re.sub(r"^(?:https?://(?:www\.)?|mailto:)", "", href).rstrip("/") or href


def _total(kind: str, values: list[float], filled: int) -> float | None:
    """A column's total over its numbers (``filled`` is what ``count`` counts)."""
    if kind == "count":
        return float(filled)
    if not values:
        return None
    if kind == "sum":
        return math.fsum(values)
    if kind == "avg":
        return math.fsum(values) / len(values)
    return min(values) if kind == "min" else max(values)


@dataclass(frozen=True)
class _Column:
    """One column as the page draws it."""

    key: str
    label: str
    kind: str
    unit: str
    decimals: int
    total: str
    formula: str
    frozen: str
    """``f1`` … ``f3`` for a leading column that stays in view, else empty."""

    @property
    def numeric(self) -> bool:
        return self.kind in _NUMERIC

    @property
    def align(self) -> str:
        return "n" if self.numeric else "c" if self.kind == "check" else ""


def _read(sheet: dict[str, Any]) -> tuple[list[_Column], list[dict[str, Any]]]:
    """A normalized sheet as columns to draw and rows with their formulas computed."""
    raw_columns = [c for c in as_list(sheet.get("columns"), MAX_COLUMNS) if isinstance(c, dict)]
    raw_rows = [r for r in as_list(sheet.get("rows"), MAX_ROWS) if isinstance(r, dict)]
    rows = _filled(raw_rows, _formula_order(raw_columns, str(sheet.get("name") or "")))
    freeze = int(bounded(sheet.get("freeze"), 0, MAX_FREEZE, 1))
    columns: list[_Column] = []
    for index, raw in enumerate(raw_columns):
        key = str(raw.get("key") or "")
        kind = _kind(raw, rows)
        values = [float(row[key]) for row in rows if _is_number(row.get(key))]
        total = pick(raw.get("total"), TOTALS, "")
        if total != "count" and kind not in _NUMERIC and kind != "check":
            total = ""
        columns.append(
            _Column(
                key=key,
                label=str(raw.get("label") or key),
                kind=kind,
                unit=str(raw.get("unit") or "") if kind in _NUMERIC else "",
                decimals=_decimals(raw, kind, values) if kind in _NUMERIC else 0,
                total=total,
                formula=str(raw.get("formula") or ""),
                frozen=f"f{index + 1}" if index < freeze else "",
            )
        )
    return columns, rows


# ------------------------------------------------------------------ rendering

_ICON_SEARCH: Final[str] = (
    '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.25"/>'
    '<path d="M10.25 10.25 13.5 13.5"/></svg>'
)
_ICON_ROWS: Final[str] = (
    '<svg viewBox="0 0 16 16" aria-hidden="true">'
    '<path d="M2.5 4.25h11M2.5 8h11M2.5 11.75h11"/></svg>'
)
_ICON_EMPTY: Final[str] = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" '
    'rx="2.5"/><path d="M3.5 9.5h17M9.5 9.5v10"/></svg>'
)
_ICON_NONE: Final[str] = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/>'
    '<path d="M16 16l4 4"/></svg>'
)
_ICON_SORT: Final[str] = (
    '<svg class="ar" viewBox="0 0 12 12" aria-hidden="true">'
    '<path d="M6 9.75v-7.5M2.75 5.5 6 2.25 9.25 5.5"/></svg>'
)
#: The check mark every checked cell points at, drawn once.
_SYMBOLS: Final[str] = (
    '<svg class="visually-hidden" width="0" height="0" aria-hidden="true">'
    '<symbol id="sx-ck" viewBox="0 0 16 16">'
    '<rect x="1" y="1" width="14" height="14" rx="4" fill="currentColor"/>'
    '<path d="M4.6 8.3l2.3 2.3 4.5-5" fill="none" stroke="var(--bg)" stroke-width="1.75" '
    'stroke-linecap="round" stroke-linejoin="round"/></symbol></svg>'
)
_CHECK_ON: Final[str] = '<svg class="ck" role="img" aria-label="✓"><use href="#sx-ck"/></svg>'
_CHECK_OFF: Final[str] = '<span class="ck off" role="img" aria-label="–"></span>'

_PAGE_CSS: Final[str] = r"""
.sx{display:flex;flex-direction:column;height:100%;min-height:0;font-size:14px;line-height:20px}
.sx-head{flex:none;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;
  gap:10px 24px;padding:14px 20px 13px;border-bottom:1px solid var(--line-2)}
.sx-id{flex:1 1 300px;min-width:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:0 14px}
.sx-id h1{max-width:100%;font-size:18px;line-height:28px;letter-spacing:-.01em;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.sx-id .node-meta{margin:0}
.sx-id .node-note,.sx-note{max-width:100%;margin:0;color:var(--ink-2);font-size:14px;
  line-height:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx-tools{flex:0 1 auto;display:flex;align-items:center;gap:14px;min-width:0}
.sx-tools svg{flex:none;width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.5;
  stroke-linecap:round;stroke-linejoin:round}
.sx-filter{display:flex;align-items:center;gap:8px;width:240px;min-width:0;height:32px;
  padding:0 10px;border:1px solid var(--line-2);border-radius:8px;background:var(--bg);
  color:var(--ink-3);cursor:text}
.sx-filter:focus-within{border-color:var(--accent);
  outline:2px solid color-mix(in srgb,var(--accent) 28%,transparent);outline-offset:0}
.sx-filter input{flex:1;min-width:0;height:100%;padding:0;border:0;outline:0;
  background:transparent;color:var(--ink);font-size:14px;appearance:none;-webkit-appearance:none}
.sx-filter input::placeholder{color:var(--ink-3);opacity:1}
.sx-filter input::-webkit-search-decoration{-webkit-appearance:none}
.sx-count{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.sx-count svg{color:var(--ink-3)}
.sx-main{position:relative;flex:1 1 auto;min-height:0}
.sx-sheet{position:absolute;inset:0;display:flex;flex-direction:column}
.sx-sheet.is-off,.sx-name{display:none}
.sx-scroll{flex:1 1 auto;min-height:0;overflow:auto;overscroll-behavior:contain;
  scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}
.sx-grid{min-width:100%;border-collapse:separate;border-spacing:0;
  font-variant-numeric:tabular-nums}
.sx-grid th,.sx-grid td{height:36px;max-width:340px;padding:0 12px;
  border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--bg);
  font-weight:400;text-align:left;vertical-align:middle;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;outline:0}
.sx-grid thead th{position:sticky;top:0;z-index:3;border-bottom-color:var(--line-2);
  color:var(--ink-2);font-weight:500;cursor:pointer;user-select:none;-webkit-user-select:none}
.sx-grid thead th:hover,.sx-grid thead th.cur,.sx-grid thead th[aria-sort$="ending"]{
  color:var(--ink)}
.sx-grid thead th[data-t]{min-width:88px}
.sx-grid thead th[data-t="text"]{min-width:128px}
.sx-grid .hc{display:flex;align-items:center;gap:6px;min-width:0}
.sx-grid .hl{min-width:0;overflow:hidden;text-overflow:ellipsis}
.sx-grid .n .hc{flex-direction:row-reverse}
.sx-grid .c .hc{justify-content:center}
.sx-grid .ar{flex:none;width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1.5;
  stroke-linecap:round;stroke-linejoin:round;opacity:0}
.sx-grid thead th:hover .ar{opacity:.4}
.sx-grid thead th[aria-sort$="ending"] .ar{opacity:1}
.sx-grid thead th[aria-sort="descending"] .ar{transform:rotate(180deg)}
.sx-grid .n{text-align:right}
.sx-grid .c{text-align:center}
.sx-grid .s,.sx-grid .u{color:var(--ink-2)}
.sx-grid .g{position:sticky;left:0;z-index:2;width:44px;min-width:44px;max-width:44px;
  padding:0 4px;color:var(--ink-3);font-size:12px;text-align:center;cursor:default;
  user-select:none;-webkit-user-select:none}
.sx-grid tbody{counter-reset:sx-row}
.sx-grid tbody tr{counter-increment:sx-row}
.sx-grid tbody .g::before{content:counter(sx-row)}
.sx-grid tbody tr.cur .g{color:var(--ink)}
.sx-grid .f1,.sx-grid .f2,.sx-grid .f3{position:sticky;z-index:2}
.sx-grid .f1{left:var(--f1,44px)}
.sx-grid .f2{left:var(--f2,auto)}
.sx-grid .f3{left:var(--f3,auto)}
.sx-grid[data-fz="0"] .f1,.sx-grid[data-fz="0"] .f2,.sx-grid[data-fz="0"] .f3,
.sx-grid[data-fz="1"] .f2,.sx-grid[data-fz="1"] .f3,.sx-grid[data-fz="2"] .f3{left:auto}
.sx-grid[data-fz="0"] .g,.sx-grid[data-fz="1"] .f1,.sx-grid[data-fz="2"] .f2,
.sx-grid[data-fz="3"] .f3{border-right-color:var(--line-2)}
.sx-grid thead .g,.sx-grid thead .f1,.sx-grid thead .f2,.sx-grid thead .f3,
.sx-grid tfoot .g,.sx-grid tfoot .f1,.sx-grid tfoot .f2,.sx-grid tfoot .f3{z-index:5}
.sx-grid .x{width:100%;max-width:none;padding:0;border-right:0;cursor:default}
.sx-grid tbody tr:hover td{background:var(--bg-2)}
.sx-grid .sel{outline:2px solid var(--accent);outline-offset:-2px}
.sx-grid a{color:var(--ink);text-decoration-color:var(--line-2)}
.sx-grid a:hover{color:var(--accent);text-decoration-color:currentColor}
.sx-grid .chip{vertical-align:middle}
.sx-grid .ck{display:inline-block;width:16px;height:16px;vertical-align:-3px;color:var(--ink)}
.sx-grid .ck.off{border:1.5px solid var(--line-2);border-radius:4px}
.sx-grid tfoot td{position:sticky;bottom:0;z-index:3;font-weight:600;overflow:visible}
.sx-grid tfoot td::before{content:"";position:absolute;left:0;right:-1px;top:-1px;height:1px;
  background:var(--line-2)}
.sx-grid .tc{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.sx-grid .c .tc{justify-content:center;gap:6px}
.sx-grid .tk{color:var(--ink-3);font-size:12px;font-weight:500}
.sx-empty{position:sticky;left:0;display:flex;flex-direction:column;align-items:center;gap:10px;
  padding:72px 16px;color:var(--ink-3);text-align:center}
.sx-empty svg{width:28px;height:28px;fill:none;stroke:currentColor;stroke-width:1.5;
  stroke-linecap:round;stroke-linejoin:round}
.sx-tabs{position:relative;z-index:6;flex:none;display:flex;gap:2px;height:41px;
  margin-top:-1px;padding:0 12px;overflow-x:auto;border-top:1px solid var(--line-2);
  scrollbar-width:none}
.sx-tabs button{position:relative;flex:none;appearance:none;max-width:220px;padding:0 12px;
  border:0;background:transparent;color:var(--ink-2);font:500 14px/20px var(--font);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.sx-tabs button:hover{color:var(--ink)}
.sx-tabs button[aria-selected="true"]{color:var(--ink)}
.sx-tabs button[aria-selected="true"]::before{content:"";position:absolute;left:12px;right:12px;
  top:0;height:2px;background:var(--ink)}
.sx-tabs button:focus-visible{outline-offset:-3px;border-radius:6px}
:root[data-node-mode="edit"] [data-at]{-webkit-user-select:text;user-select:text}
:root[data-node-mode="edit"] .sx-grid td[data-at]{outline-offset:-2px;border-radius:0}
:root[data-node-mode="edit"] .sx-grid td[data-at]:focus{white-space:nowrap;text-overflow:clip}
:root[data-node-mode="edit"] .sx-grid .hl[data-at]{min-width:1ch}
:root[data-node-mode="edit"] .sx-grid thead th.sel:focus-within{outline:0}
:root[data-node-mode="edit"] .sx-tn[data-at]{display:inline-block;min-width:1ch}
@media (max-width:560px){
.sx-head{gap:8px 16px;padding:12px 14px 11px}
.sx-tools{flex:1 1 100%}
.sx-filter{flex:1;width:auto}
.sx-grid th,.sx-grid td{max-width:240px}
.sx-grid .g{width:36px;min-width:36px;max-width:36px}
.sx-grid .f1{left:var(--f1,36px)}
.sx-tabs{padding:0 6px}}
@media print{
html,body{height:auto}
body.fill{overflow:visible}
.sx{display:block;height:auto}
.sx-head{padding:0 0 12px}
.sx-tools,.sx-tabs{display:none}
.sx-main{position:static}
.sx-sheet,.sx-sheet.is-off{position:static;display:block;margin-top:24px}
.sx-name{display:block;margin-bottom:8px;font-size:16px;line-height:24px}
.sx-scroll{overflow:visible}
.sx-grid{width:100%;min-width:0;font-size:12px}
.sx-grid th,.sx-grid td,.sx-grid thead th,.sx-grid tfoot td{position:static;max-width:none;
  height:28px;padding:0 8px;white-space:normal;overflow:visible}
.sx-grid thead th[data-t]{min-width:0!important}
.sx-grid .n,.sx-grid .g{white-space:nowrap}
.sx-grid .x{display:none}
.sx-grid tfoot{display:table-row-group}
.sx-grid tfoot td{border-top:1px solid var(--line-2)}
.sx-grid tfoot td::before{display:none}
.sx-grid .sel{outline:0}
.sx-grid .ar{display:none}}
"""

# Everything the grid does on the page: numbers and dates in the viewer's
# locale, the filter, the sort, the totals of the rows left visible, the
# selected cell and its arrow keys, the frozen columns' offsets, the tabs and
# web links handed to the app. It reads the grid's own markup (data-value,
# data-t, data-u, data-d, data-total); no value from a spec is written into it.
_PAGE_JS: Final[str] = r"""
(function(){
"use strict";
var d=document,lang=navigator.language||undefined;
function each(l,f){Array.prototype.forEach.call(l,f);}
function nf(o){try{return new Intl.NumberFormat(lang,o);}catch(e){return null;}}
var plain=nf({maximumFractionDigits:0}),plain2=nf({maximumFractionDigits:2}),coll=null,df={};
try{coll=new Intl.Collator(lang,{numeric:true,sensitivity:"base"});}catch(e){}
function compare(a,b){return coll?coll.compare(a,b):(a<b?-1:a>b?1:0);}
function make(c,dg){
  var o={minimumFractionDigits:dg,maximumFractionDigits:dg},f=null;
  if(c.t==="currency"&&/^[A-Za-z]{3}$/.test(c.u)){
    f=nf({style:"currency",currency:c.u.toUpperCase(),currencyDisplay:"narrowSymbol",
      minimumFractionDigits:dg,maximumFractionDigits:dg});
    if(f){c.own=true;return f;}}
  if(c.t==="percent"){
    f=nf({style:"percent",minimumFractionDigits:dg,maximumFractionDigits:dg});
    if(f){c.own=true;c.div=100;return f;}
    c.u="%";}
  return nf(o);}
function put(el,c,v,wide){
  var f=wide?(c.fw||(c.fw=make(c,Math.max(c.d,2)))):c.f;
  el.textContent=f?f.format(c.div?v/c.div:v):String(v);
  if(c.u&&!c.own){var s=d.createElement("span");s.className="u";
    s.textContent=" "+c.u;el.appendChild(s);}}
var dre=/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/;
function dateText(v){
  var m=dre.exec(v);if(!m)return null;
  try{
    var k=m[4]?"t":"d";
    if(!df[k])df[k]=new Intl.DateTimeFormat(lang,
      m[4]?{dateStyle:"medium",timeStyle:"short"}:{dateStyle:"medium"});
    var dt=new Date(+m[1],+m[2]-1,+m[3],m[4]?+m[4]:0,m[5]?+m[5]:0);
    return isNaN(dt.getTime())?null:df[k].format(dt);
  }catch(e){return null;}}
var input=d.querySelector(".sx-filter input"),countEl=d.querySelector("[data-count]");
function Sheet(el){
  var S={el:el,scroll:el.querySelector(".sx-scroll"),table:el.querySelector("table"),
    cols:[],sort:null,dir:0,sel:null,shown:0,formatted:false,locked:false};
  S.head=S.table.tHead.rows[0];S.body=S.table.tBodies[0];
  S.rows=Array.prototype.slice.call(S.body.rows);S.n=S.rows.length;S.shown=S.n;
  S.foot=S.table.tFoot?S.table.tFoot.rows[0]:null;
  S.none=el.querySelector(".sx-none");
  each(S.head.cells,function(th,i){
    if(!th.hasAttribute("data-t"))return;
    var c={i:i,th:th,t:th.getAttribute("data-t"),u:th.getAttribute("data-u")||"",
      d:Number(th.getAttribute("data-d"))||0,total:th.getAttribute("data-total")||""};
    c.num=c.t==="number"||c.t==="currency"||c.t==="percent";
    if(c.num)c.f=make(c,c.d);
    S.cols.push(c);});
  S.entry=S.table.querySelector('[tabindex="0"]');
  // A link's address and a chip's tone stay when the text of one is edited.
  each(S.body.querySelectorAll("td[data-at]"),function(td){
    if(!/\/text$/.test(td.getAttribute("data-at")))return;
    var a=td.querySelector("a[href]"),ch=td.querySelector(".chip");
    if(a)td.sxA=a.cloneNode(false);else if(ch)td.sxC=ch.className;});
  S.scroll.addEventListener("scroll",function(){clearTimeout(S.held);S.held=setTimeout(hold,200);});
  wire(S);return S;}
function draw(td,c){
  // A number or a date written out from its raw value; never in a field being typed into.
  var v=td.getAttribute("data-value");
  if(v===null||v===""||td===d.activeElement)return;
  if(c.num)put(td,c,Number(v));
  else if(c.t==="date"){var s=dateText(v);if(s)td.textContent=s;}}
function rowText(S,r){
  var raw=[];
  S.cols.forEach(function(c){
    var v=r.cells[c.i].getAttribute("data-value");
    if(v!==null&&v!==""&&(c.num||c.t==="date"))raw.push(v);});
  return (r.textContent+" "+raw.join(" ")).toLocaleLowerCase();}
function format(S){
  if(S.formatted)return;S.formatted=true;
  S.text=S.rows.map(function(r){
    S.cols.forEach(function(c){draw(r.cells[c.i],c);});
    return rowText(S,r);});}
function lock(S){
  if(S.locked||!S.head.offsetWidth)return;S.locked=true;
  var w=[];
  S.cols.forEach(function(c){w.push(c.th.offsetWidth);});
  S.cols.forEach(function(c,k){c.th.style.minWidth=w[k]+"px";});}
function measure(S){
  var t=S.table,cells=S.head.cells,fz=Number(t.getAttribute("data-freeze"))||0;
  if(!S.head.offsetWidth)return;
  var left=cells[0].offsetWidth,room=S.scroll.clientWidth*0.55,n=0,k,w;
  for(k=1;k<=fz&&k<=S.cols.length;k++){
    w=cells[k].offsetWidth;if(left+w>room)break;
    t.style.setProperty("--f"+k,left+"px");left+=w;n=k;}
  t.setAttribute("data-fz",String(n));
  S.fw=left;S.hh=S.head.offsetHeight;S.fh=S.foot?S.foot.offsetHeight:0;}
function totals(S){
  if(!S.foot)return;
  S.cols.forEach(function(c){
    if(!c.total)return;
    var out=S.foot.cells[c.i].querySelector(".tv");if(!out)return;
    var vals=[],filled=0,check=c.t==="check";
    S.rows.forEach(function(r){
      if(r.hidden)return;
      var td=r.cells[c.i],v=td.getAttribute("data-value");
      if((c.num||check)&&v!==null&&v!==""&&isFinite(Number(v)))vals.push(Number(v));
      if(check){if(v==="1")filled++;}
      else if((v!==null?v:td.textContent).trim()!=="")filled++;});
    if(c.total==="count"){out.textContent=plain?plain.format(filled):String(filled);return;}
    if(!vals.length){out.textContent="";return;}
    var r=vals[0],sum=0;
    vals.forEach(function(v){sum+=v;
      if(c.total==="min"&&v<r)r=v;if(c.total==="max"&&v>r)r=v;});
    if(c.total==="sum")r=sum;
    if(c.total==="avg")r=sum/vals.length;
    if(!c.num){out.textContent=plain2?plain2.format(r):String(r);return;}
    var p=Math.pow(10,c.d);
    put(out,c,r,c.total==="avg"&&Math.abs(Math.round(r*p)/p-r)>1e-9);});}
function count(S){
  if(!countEl)return;
  var f=function(n){return plain?plain.format(n):String(n);};
  countEl.textContent=S.shown===S.n?f(S.n):f(S.shown)+" / "+f(S.n);}
function filter(S){
  var q=input?input.value.toLocaleLowerCase().split(/\s+/).filter(Boolean):[],shown=0;
  S.rows.forEach(function(r,i){
    var ok=q.every(function(w){return S.text[i].indexOf(w)>=0;});
    if(r.hidden===ok)r.hidden=!ok;
    if(ok)shown++;});
  S.shown=shown;
  if(S.none)S.none.hidden=!(S.n>0&&shown===0);
  if(S.foot)S.foot.hidden=shown===0;
  if(S.sel&&S.sel.parentNode.hidden)pick(S,null,false);
  totals(S);count(S);}
function sortBy(S,c){
  var dir=S.sort===c?(S.dir===1?-1:0):1,rows=S.rows;
  S.cols.forEach(function(x){x.th.setAttribute("aria-sort","none");});
  S.sort=dir?c:null;S.dir=dir;
  if(dir){
    c.th.setAttribute("aria-sort",dir===1?"ascending":"descending");
    var numeric=c.num||c.t==="check";
    var keys=S.rows.map(function(r){
      var td=r.cells[c.i],v=td.getAttribute("data-value");
      if(numeric)return v===null||v===""||!isFinite(Number(v))?null:Number(v);
      v=(v!==null?v:td.textContent).trim();return v===""?null:v;});
    var order=S.rows.map(function(_,i){return i;});
    order.sort(function(a,b){
      var x=keys[a],y=keys[b];
      if(x===null||y===null)return x===y?a-b:(x===null?1:-1);
      var r=numeric?x-y:compare(x,y);
      return r?r*dir:a-b;});
    rows=order.map(function(i){return S.rows[i];});}
  var frag=d.createDocumentFragment();
  rows.forEach(function(r){frag.appendChild(r);});
  S.body.appendChild(frag);hold();}
function cellOf(S,target){
  var c=target&&target.closest?target.closest("td,th"):null;
  if(!c||!S.table.contains(c))return null;
  var section=c.parentNode.parentNode;
  if(section===S.table.tFoot||c.cellIndex<1||c.cellIndex>S.cols.length)return null;
  return c;}
function reveal(S,cell){
  var sc=S.scroll,cr=cell.getBoundingClientRect(),sr=sc.getBoundingClientRect();
  var top=sr.top+(S.hh||0),bottom=sr.top+sc.clientHeight-(S.fh||0);
  var fz=Number(S.table.getAttribute("data-fz"))||0;
  var left=sr.left+(S.fw||0),right=sr.left+sc.clientWidth;
  if(cell.parentNode!==S.head){
    if(cr.top<top)sc.scrollTop-=top-cr.top;
    else if(cr.bottom>bottom)sc.scrollTop+=cr.bottom-bottom;}
  if(cell.cellIndex>fz){
    if(cr.left<left)sc.scrollLeft-=left-cr.left;
    else if(cr.right>right)sc.scrollLeft+=cr.right-right;}}
function firstRow(S){var r=S.body.firstElementChild;
  while(r&&r.hidden)r=r.nextElementSibling;return r;}
function lastRow(S){var r=S.body.lastElementChild;
  while(r&&r.hidden)r=r.previousElementSibling;return r;}
function step(row,by){
  var r=row,n=Math.abs(by),next;
  while(n>0){
    next=by>0?r.nextElementSibling:r.previousElementSibling;
    while(next&&next.hidden)next=by>0?next.nextElementSibling:next.previousElementSibling;
    if(!next)break;
    r=next;n--;}
  return r;}
function pick(S,cell,focus){
  if(S.entry&&S.entry!==cell)S.entry.removeAttribute("tabindex");
  S.entry=null;
  if(S.sel&&S.sel!==cell){
    S.sel.classList.remove("sel");S.sel.removeAttribute("tabindex");
    S.sel.parentNode.classList.remove("cur");
    S.head.cells[S.sel.cellIndex].classList.remove("cur");}
  S.sel=cell;
  if(!cell){
    var r=firstRow(S);S.entry=(r||S.head).cells[1]||null;
    if(S.entry)S.entry.tabIndex=0;
    return;}
  cell.classList.add("sel");cell.tabIndex=0;
  if(cell.parentNode!==S.head)cell.parentNode.classList.add("cur");
  S.head.cells[cell.cellIndex].classList.add("cur");
  if(focus){cell.focus({preventScroll:true});reveal(S,cell);}}
function wire(S){
  var t=S.table;
  t.addEventListener("focusin",function(e){
    var c=cellOf(S,e.target);if(c&&c!==S.sel)pick(S,c,false);});
  t.addEventListener("click",function(e){
    var c=cellOf(S,e.target);if(!c)return;
    if(c.parentNode===S.head){
      S.cols.forEach(function(x){if(x.th===c)sortBy(S,x);});}
    pick(S,c,true);});
  t.addEventListener("keydown",function(e){
    var c=S.sel;if(!c||e.altKey)return;
    var k=e.key,row=c.parentNode,inHead=row===S.head,i=c.cellIndex,last=S.cols.length;
    var all=e.ctrlKey||e.metaKey,next=null,r;
    var page=Math.max(1,Math.floor((S.scroll.clientHeight-(S.hh||0)-(S.fh||0))/36)-1);
    if(k==="ArrowRight")next=row.cells[Math.min(last,i+1)];
    else if(k==="ArrowLeft")next=row.cells[Math.max(1,i-1)];
    else if(k==="ArrowDown"||k==="PageDown"){
      r=inHead?firstRow(S):step(row,k==="ArrowDown"?1:page);
      if(inHead&&r&&k==="PageDown")r=step(r,page-1);
      if(r)next=r.cells[i];}
    else if(k==="ArrowUp"||k==="PageUp"){
      if(inHead)next=c;
      else{r=step(row,k==="ArrowUp"?-1:-page);next=(r===row?S.head:r).cells[i];}}
    else if(k==="Home")next=all?(firstRow(S)||S.head).cells[1]:row.cells[1];
    else if(k==="End")next=all?(lastRow(S)||row).cells[last]:row.cells[last];
    else if(k==="Enter"||k===" "){
      if(inHead){e.preventDefault();
        S.cols.forEach(function(x){if(x.th===c)sortBy(S,x);});}
      else{var a=c.querySelector("a[href]");if(a){e.preventDefault();a.click();}}
      return;}
    else return;
    e.preventDefault();
    if(next&&next!==c)pick(S,next,true);});}
var sheets=[],tabs=d.querySelectorAll('.sx-tabs [role="tab"]'),cur=0;
each(d.querySelectorAll(".sx-sheet"),function(el){sheets.push(Sheet(el));});
function show(i,focus){
  if(!sheets[i])return;
  cur=i;
  sheets.forEach(function(S,j){S.el.classList.toggle("is-off",j!==i);});
  each(tabs,function(t,j){
    t.setAttribute("aria-selected",j===i?"true":"false");t.tabIndex=j===i?0:-1;});
  var S=sheets[i];format(S);totals(S);lock(S);measure(S);filter(S);
  if(focus&&tabs[i]){tabs[i].focus();}
  hold();}
each(tabs,function(t,j){
  t.addEventListener("click",function(){show(j,false);});
  // In edit mode a click on a tab lands in its name (a field): the sheet opens all the same.
  t.addEventListener("focusin",function(){if(editing()&&j!==cur)show(j,false);});
  t.addEventListener("keydown",function(e){
    var to=e.key==="ArrowRight"?j+1:e.key==="ArrowLeft"?j-1:
      e.key==="Home"?0:e.key==="End"?tabs.length-1:-1;
    if(to<0||to>=tabs.length||to===j)return;
    e.preventDefault();show(to,true);});});
if(input){
  input.addEventListener("input",function(){if(sheets[cur])filter(sheets[cur]);});
  input.addEventListener("keydown",function(e){
    var S=sheets[cur];
    if(e.key==="Escape"&&input.value){input.value="";if(S)filter(S);e.preventDefault();}
    else if((e.key==="ArrowDown"||e.key==="Enter")&&S){
      var r=firstRow(S),c=S.sel||(r?r.cells[1]:null);
      if(c){e.preventDefault();pick(S,c,true);}}});}
d.addEventListener("keydown",function(e){
  var el=d.activeElement,tag=el?el.tagName:"";
  if(e.key!=="/"||e.ctrlKey||e.metaKey||e.altKey||tag==="INPUT"||tag==="TEXTAREA"||!input)return;
  e.preventDefault();input.focus();input.select();});
d.addEventListener("click",function(e){
  var a=e.target.closest?e.target.closest("a[href]"):null;
  var h=a?(a.getAttribute("href")||"").trim():"";
  if(h.indexOf("http://")!==0&&h.indexOf("https://")!==0)return;
  e.preventDefault();
  if(window.parent!==window){window.parent.postMessage({type:"dodaios-open-link",href:h},"*");}
  else{location.href=h;}});
// Edit mode (nodes/bridge.py): the bridge turns the marked texts into fields and
// posts each change. Whether the page must be drawn again is often known only
// once the value is typed, and the bridge reads data-refresh when the field is
// left: a number the page cannot read for sure, one with more decimals than its
// column shows, a date only Python reads, an emptied cell (its row may go).
// Otherwise the page writes the saved value into its own grid, and the reader
// keeps the open sheet, the sort, the filter and the place in the grid.
function editing(){return d.documentElement.getAttribute("data-node-mode")==="edit";}
function sheetOf(el){
  for(var k=0;k<sheets.length;k++)if(sheets[k].table.contains(el))return sheets[k];
  return null;}
function colOf(S,td){
  for(var k=0;k<S.cols.length;k++)if(S.cols[k].i===td.cellIndex)return S.cols[k];
  return null;}
function numberOf(s){
  // Only what reads one way in every notation: "40,62", "1.234,5", "1200.5", "-3".
  s=String(s).replace(/[\s\u00a0\u202f]/g,"").replace(/^[\u2212\u2013]/,"-");
  var m=/^([+-]?)(\d+)$/.exec(s),n=null;
  if(m)n=Number(m[1]+m[2]);
  else if((m=/^([+-]?)(\d*)([.,])(\d+)$/.exec(s))){
    // "1.234" is a thousand in one notation and a decimal in another.
    if(!(m[4].length===3&&m[2].length>0&&m[2].length<4&&m[2]!=="0"))
      n=Number(m[1]+(m[2]||"0")+"."+m[4]);}
  else if((m=/^([+-]?)(\d{1,3}([.,])\d{3}(?:\3\d{3})*)(?:([.,])(\d+))?$/.exec(s))){
    if(!m[4]||m[4]!==m[3])n=Number(m[1]+m[2].split(m[3]).join("")+(m[4]?"."+m[5]:""));}
  return n!==null&&isFinite(n)?n:null;}
function places(n){var t=Math.abs(n).toFixed(2).replace(/0+$/,"");return t.length-t.indexOf(".")-1;}
var loose=/^\d{4}-\d{2}-\d{2}[T ]/;
d.addEventListener("input",function(e){
  var el=e.target,at=el&&el.getAttribute?el.getAttribute("data-at"):null;
  if(!at||at.indexOf("/sheets/")!==0)return;
  if(el.sxR===undefined)el.sxR=el.hasAttribute("data-refresh");
  var v=(el.innerText||el.textContent||"").replace(/\u00a0/g," ").trim(),S=sheetOf(el);
  var th=S&&el.tagName==="TD"?S.head.cells[el.cellIndex]:null,again=el.sxR||v==="";
  if(!again&&el.getAttribute("data-as")==="number"){
    var n=numberOf(v),dg=th?th.getAttribute("data-d"):null;
    again=n===null||(dg!==null&&places(n)>Number(dg));}
  if(!again&&th&&th.getAttribute("data-t")==="date")again=loose.test(v)&&!dre.test(v);
  if(again)el.setAttribute("data-refresh","");else el.removeAttribute("data-refresh");});
function hold(){
  // The reader's place in the hash, which the bridge carries across a redraw:
  // "#s1-o2d-t480" is the second sheet, sorted down by its third column, 480 px down.
  var S=sheets[cur];if(!S||!editing())return;
  var h="#s"+cur,k=S.sort?S.cols.indexOf(S.sort):-1;
  var t=Math.round(S.scroll.scrollTop),l=Math.round(S.scroll.scrollLeft);
  if(k>=0)h+="-o"+k+(S.dir===1?"a":"d");
  if(t>0)h+="-t"+t;
  if(l>0)h+="-l"+l;
  if(h!==location.hash){try{history.replaceState(null,"",h);}catch(e){}}}
function anchors(){
  // A link in a cell is no Tab stop (tabindex -1), which also lets a click focus the
  // link itself; in edit mode the click must land in the cell's field instead.
  var on=editing();
  each(d.querySelectorAll(".sx-grid td[data-at] a[href]"),function(a){
    if(on)a.removeAttribute("tabindex");else a.setAttribute("tabindex","-1");});
  hold();}
if(window.MutationObserver)new MutationObserver(anchors).observe(d.documentElement,
  {attributes:true,attributeFilter:["data-node-mode"]});
function check(on){
  var o;
  if(!on){o=d.createElement("span");o.className="ck off";}
  else{
    var ns="http://www.w3.org/2000/svg",u=d.createElementNS(ns,"use");
    o=d.createElementNS(ns,"svg");o.setAttribute("class","ck");
    u.setAttribute("href","#sx-ck");o.appendChild(u);}
  o.setAttribute("role","img");o.setAttribute("aria-label",on?"\u2713":"\u2013");
  return o;}
function linkLabel(t,h){
  return t&&t!==h?t:(h.replace(/^(?:https?:\/\/(?:www\.)?|mailto:)/,"").replace(/\/+$/,"")||h);}
function paint(S,c,el){
  // The saved cell drawn the way the page draws every other cell.
  if(el===d.activeElement){el.sxLater=true;return;}
  var as=el.getAttribute("data-as"),v=el.getAttribute("data-value"),t=(el.textContent||"").trim();
  var src=el.getAttribute("data-src"),o;
  if(as==="toggle"){el.textContent="";el.appendChild(check(v==="1"||src==="true"));}
  else if(as==="number"){
    if(c.num&&v!==null)draw(el,c);
    else if(src!==null&&(src===""||numberOf(src)!==null))el.textContent=src;}
  else if(c.t==="date"){if(v!==null)draw(el,c);}
  else if(el.sxA){o=el.sxA.cloneNode(false);o.textContent=linkLabel(t,o.getAttribute("href"));
    if(editing())o.removeAttribute("tabindex");
    el.textContent="";el.appendChild(o);}
  else if(el.sxC){o=d.createElement("span");o.className=el.sxC;o.textContent=t;
    el.textContent="";el.appendChild(o);}
  else if(c.t==="text"){
    if(t.length>48)el.setAttribute("title",t);else el.removeAttribute("title");}
  var i=S.rows.indexOf(el.parentNode);
  if(S.text&&i>=0)S.text[i]=rowText(S,el.parentNode);
  totals(S);}
d.addEventListener("node-field-saved",function(e){
  var el=e.target,v=e.detail?String(e.detail.value):"",t=v.trim(),S=sheetOf(el),c,k;
  if(!S){
    // A sheet's name on its tab: the panel and the printed heading follow.
    k=Array.prototype.indexOf.call(tabs,el.closest?el.closest('[role="tab"]'):null);
    if(k>=0&&sheets[k]){
      sheets[k].table.setAttribute("aria-label",t);
      var h=sheets[k].el.querySelector(".sx-name");if(h)h.textContent=t;}
    return;}
  if(el.tagName!=="TD"){measure(S);return;}
  c=colOf(S,el);if(!c)return;
  var as=el.getAttribute("data-as");
  if(as==="toggle")el.setAttribute("data-value",v==="true"?"1":"0");
  else if(as==="number"){
    var n=t===""?null:numberOf(t);
    if(n!==null){el.setAttribute("data-src",String(n));if(c.num)el.setAttribute("data-value",String(n));}
    else if(t===""){el.setAttribute("data-src","");el.removeAttribute("data-value");}}
  else if(c.t==="date"){
    if(dre.test(t))el.setAttribute("data-value",t);else el.removeAttribute("data-value");}
  paint(S,c,el);});
d.addEventListener("focusout",function(e){
  // A saved value that arrived while its field was typed into again.
  var el=e.target;
  if(!el||!el.sxLater||/ is-saving/.test(el.className))return;
  el.sxLater=false;var S=sheetOf(el),c=S?colOf(S,el):null;if(c)paint(S,c,el);});
addEventListener("resize",function(){if(sheets[cur])measure(sheets[cur]);});
addEventListener("beforeprint",function(){sheets.forEach(format);sheets.forEach(totals);});
function goTo(h){
  // A page drawn again after an edit opens at the place its hash names (see hold);
  // the bridge sets that hash when the app hands it back.
  var m=/^#s(\d{1,2})(?:-o(\d{1,2})([ad]))?(?:-t(\d{1,7}))?(?:-l(\d{1,7}))?$/.exec(h||"");
  var S=m?sheets[Number(m[1])]:null;if(!S)return;
  var c=m[2]?S.cols[Number(m[2])]||null:null,dir=c?(m[3]==="d"?-1:1):0;
  if(S!==sheets[cur])show(Number(m[1]),false);
  for(var n=0;n<3&&(S.sort!==c||S.dir!==dir);n++)sortBy(S,c||S.sort);
  S.scroll.scrollTop=Number(m[4]||0);S.scroll.scrollLeft=Number(m[5]||0);}
addEventListener("hashchange",function(){goTo(location.hash);});
show(0,false);
goTo(location.hash);
})();
"""


def _number_html(value: float, column: _Column, decimals: int, language: str) -> str:
    """A number as the fallback text the page script replaces."""
    text = esc(_format(value, decimals, language))
    if column.kind == "percent":
        return text + (" %" if _comma(language) else "%")
    if column.unit:
        return f'{text}<span class="u"> {esc(column.unit)}</span>'
    return text


def _chip(value: Any) -> str:
    text, tone = _status_tone(value)
    if not text:
        return ""
    klass = f"chip {tone}" if tone else "chip"
    return f'<span class="{klass}">{esc(text)}</span>'


def _anchor(value: Any) -> str:
    if isinstance(value, dict):
        href = safe_link(value.get("href"))
        label = _link_label(str(value.get("text") or ""), href)
        if href:
            # Not a Tab stop of its own: Enter on the selected cell opens it.
            return (
                f'<a href="{attr(href)}" rel="noopener noreferrer" tabindex="-1">'
                f"{esc(label)}</a>"
            )
        return esc(label)
    return esc(_text_of(value))


def _text_html(value: Any) -> tuple[str, str]:
    """A text cell's content and, for a long text, the attribute that shows all of it."""
    text = _text_of(value)
    return esc(text), f' title="{attr(text)}"' if len(text) > 48 else ""


def _pointer(*parts: object) -> str:
    """A JSON Pointer to a place in the stored spec."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _mark(at: str) -> str:
    return f' data-at="{attr(at)}"'


def _cell_marks(value: Any, column: _Column, at: str, refresh: bool) -> str:
    """What makes one body cell a field of the edit mode (see :mod:`dodaios.nodes.bridge`).

    ``at`` is the cell's place in the stored spec, ``refresh`` whether every
    change of the sheet's cells has the page drawn again. Empty for a cell
    that offers nothing to edit.
    """
    empty = value is None or value == ""
    marks = ""
    redraw = refresh
    if isinstance(value, bool) or (empty and column.kind == "check"):
        marks = f' data-as="toggle" data-src="{"true" if value else "false"}"'
    elif empty:
        if column.numeric:
            marks = ' data-as="number" data-src=""'
        elif column.kind == "date":
            marks = ' data-src=""'
        elif column.kind in ("status", "link"):
            redraw = True  # what is typed becomes a chip or a link, drawn by Python
    elif _is_number(value):
        marks = f' data-as="number" data-src="{attr(_raw(value))}"'
    elif column.numeric:
        redraw = True  # text in a number column ("n/a"): a number typed there becomes one
    elif column.kind == "date":
        marks = f' data-src="{attr(_text_of(value))}"'
    elif isinstance(value, dict):
        # A link or a status chip: its text is the value; the address and the tone stay.
        if not isinstance(value.get("text"), str):
            return ""
        at += "/text"
        if "href" in value:
            marks = f' data-src="{attr(value["text"])}"'
    elif column.kind in ("status", "link"):
        redraw = True  # a status word's tone, or whether a text is an address, is Python's
    return f"{_mark(at)}{marks}{' data-refresh' if redraw else ''}"


def _cell_html(
    value: Any,
    column: _Column,
    language: str,
    entry: bool,
    at: str = "",
    refresh: bool = False,
) -> str:
    """One body cell. ``entry`` marks the cell the Tab key lands on; ``at`` is
    its place in the stored spec when it can be edited (see :func:`_cell_marks`)."""
    classes = [name for name in (column.align, column.frozen) if name]
    extra = ' tabindex="0"' if entry else ""
    inner = ""
    if value is None or value == "":
        pass
    elif column.numeric:
        if _is_number(value):
            extra += f' data-value="{attr(_raw(value))}"'
            inner = _number_html(float(value), column, column.decimals, language)
        else:
            classes.append("s")
            inner = esc(_text_of(value))
    elif isinstance(value, bool):
        extra += f' data-value="{1 if value else 0}"'
        inner = _CHECK_ON if value else _CHECK_OFF
    elif column.kind == "date":
        iso = _iso(value)
        if iso:
            extra += f' data-value="{attr(iso)}"'
        inner = esc(_text_of(value))
    elif column.kind == "status" or (isinstance(value, dict) and "tone" in value):
        inner = _chip(value)
    elif column.kind == "link" or isinstance(value, dict):
        inner = _anchor(value)
    elif _is_number(value):
        inner = esc(_raw(value))
    else:
        inner, title = _text_html(value)
        extra += title
    klass = f' class="{" ".join(classes)}"' if classes else ""
    marks = _cell_marks(value, column, at, refresh) if at else ""
    return f"<td{klass}{extra}{marks}>{inner}</td>"


def _head_html(column: _Column, entry: bool, at: str = "") -> str:
    """One column's head; ``at`` is its label's place in the stored spec when editable."""
    classes = " ".join(name for name in (column.align, column.frozen) if name)
    parts = [f' class="{classes}"' if classes else "", f' data-t="{attr(column.kind)}"']
    if column.numeric:
        unit = _currency_code(column.unit) if column.kind == "currency" else column.unit
        parts.append(f' data-u="{attr(unit)}" data-d="{column.decimals}"')
    if column.total:
        parts.append(f' data-total="{attr(column.total)}"')
    if column.formula:
        parts.append(f' title="= {attr(column.formula)}"')
    if entry:
        parts.append(' tabindex="0"')
    return (
        f'<th scope="col"{"".join(parts)} aria-sort="none"><span class="hc">'
        f'<span class="hl"{_mark(at) if at else ""}>{esc(column.label)}</span>'
        f"{_ICON_SORT}</span></th>"
    )


def _total_html(column: _Column, rows: list[dict[str, Any]], language: str) -> str:
    # A count under a text column is a number too: it sits at the right edge.
    classes = " ".join(name for name in (column.align or "n", column.frozen) if name)
    if not column.total:
        blank = " ".join(name for name in (column.align, column.frozen) if name)
        return f'<td class="{blank}"></td>' if blank else "<td></td>"
    cells = [row.get(column.key) for row in rows]
    if column.kind == "check":
        values = [1.0 if cell else 0.0 for cell in cells if isinstance(cell, bool)]
        filled = sum(1 for cell in cells if cell is True)
    else:
        values = [float(cell) for cell in cells if _is_number(cell)]
        filled = sum(1 for cell in cells if cell is not None and cell != "")
    result = _total(column.total, values, filled)
    if result is None:
        text = ""
    elif column.total == "count":
        text = esc(_format(result, 0, language))
    elif not column.numeric:
        text = esc(_format(result, _needed_decimals(result), language))
    else:
        decimals = column.decimals
        if column.total == "avg" and abs(round(result, decimals) - result) > 1e-9:
            decimals = max(decimals, 2)
        text = _number_html(result, column, decimals, language)
    mark = esc(_TOTAL_MARKS[column.total])
    # A flex line, not a float: the column must grow to hold the mark and the value.
    return (
        f'<td class="{classes}"><span class="tc">'
        f'<span class="tk" title="{attr(column.total)}">{mark}</span>'
        f'<span class="tv">{text}</span></span></td>'
    )


def _sheet_html(
    sheet: dict[str, Any],
    index: int,
    several: bool,
    language: str,
    stored: Any = None,
) -> str:
    """One sheet: its grid, and what stands in for the rows when there are none.

    ``stored`` is the sheet as the node's spec holds it. Its cells and labels
    are offered for editing only where it holds exactly what is drawn, so a
    field's place (``/sheets/0/rows/3/qty``) is always the stored row's, in
    whatever order the reader has sorted the grid.
    """
    columns, rows = _read(sheet)
    name = str(sheet.get("name") or "")
    freeze = sum(1 for column in columns if column.frozen)
    kept = stored if isinstance(stored, dict) else {}
    base = _pointer("sheets", index)
    labels = kept.get("columns") == sheet.get("columns")
    cells_kept = kept.get("rows") == sheet.get("rows")
    # A formula or a total is computed from the other cells: the page is drawn again.
    refresh = any(column.formula or column.total for column in columns)
    head = '<th class="g"></th>' + "".join(
        _head_html(
            column,
            entry=not rows and position == 0,
            at=base + _pointer("columns", position, "label") if labels else "",
        )
        for position, column in enumerate(columns)
    )
    body: list[str] = []
    for row_index, row in enumerate(rows):
        cells = "".join(
            _cell_html(
                row.get(column.key),
                column,
                language,
                row_index == 0 and position == 0,
                at=(
                    base + _pointer("rows", row_index, column.key)
                    if cells_kept and not column.formula
                    else ""
                ),
                refresh=refresh,
            )
            for position, column in enumerate(columns)
        )
        body.append(f'<tr><td class="g"></td>{cells}<td class="x"></td></tr>')
    foot = ""
    if rows and any(column.total for column in columns):
        totals = "".join(_total_html(column, rows, language) for column in columns)
        foot = f'<tfoot><tr><td class="g"></td>{totals}<td class="x"></td></tr></tfoot>'
    state = (
        f'<div class="sx-empty sx-none" hidden>{_ICON_NONE}<p>No matching rows</p></div>'
        if rows
        else f'<div class="sx-empty">{_ICON_EMPTY}<p>No rows yet</p></div>'
    )
    panel = f' role="tabpanel" aria-labelledby="sx-tab-{index}"' if several else ""
    title = f'<h2 class="sx-name">{esc(name)}</h2>' if several else ""
    return (
        f'<section class="sx-sheet{" is-off" if index else ""}" id="sx-sheet-{index}"{panel}>'
        f'{title}<div class="sx-scroll">'
        f'<table class="sx-grid" role="grid" aria-readonly="true" aria-label="{attr(name)}" '
        f'data-freeze="{freeze}" data-fz="{freeze}">'
        f'<thead><tr>{head}<th class="x"></th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody>{foot}</table>{state}</div></section>"
    )


def _name_mark(stored: list[Any], index: int, sheet: dict[str, Any]) -> str:
    """The edit mark of a sheet's name on its tab, when the stored spec holds that name."""
    kept = stored[index] if index < len(stored) and isinstance(stored[index], dict) else {}
    return _mark(_pointer("sheets", index, "name")) if kept.get("name") == sheet["name"] else ""


def render(node: Any) -> str:
    """The node as one self-contained page (see :func:`dodaios.nodes.shell.document`)."""
    try:
        spec = normalize(getattr(node, "spec", None))
    except NodeError:  # a spec no sheet can be read from still gets a page: an empty one
        spec = {"sheets": []}
    sheets: list[dict[str, Any]] = spec["sheets"]
    # What the reader can write into in edit mode (`nodes/bridge.py`) is marked
    # with its place in the spec AS STORED; a value is offered only where the
    # stored spec holds what the page draws (the store keeps it normalized).
    raw = getattr(node, "spec", None)
    raw = raw if isinstance(raw, dict) else {}
    stored = raw.get("sheets") if isinstance(raw.get("sheets"), list) else []
    language = str(getattr(node, "language", "") or "en")
    several = len(sheets) > 1
    count = len(sheets[0]["rows"]) if sheets else 0
    note = spec.get("note")
    note_mark = _mark("/note") if note and raw.get("note") == note else ""
    note_html = f'<p class="sx-note"{note_mark}>{esc(note)}</p>' if note else ""
    head = (
        '<header class="sx-head"><div class="sx-id">'
        f'<h1 data-at="@title">{esc(getattr(node, "title", ""))}</h1>'
        f"{upkeep_meta(node)}{note_html}</div>"
        '<div class="sx-tools">'
        f'<label class="sx-filter">{_ICON_SEARCH}'
        '<span class="visually-hidden">Filter rows</span>'
        '<input type="search" placeholder="Filter" autocomplete="off" spellcheck="false">'
        "</label>"
        f'<span class="sx-count" aria-live="polite">{_ICON_ROWS}'
        f"<span data-count>{esc(_format(count, 0, language))}</span></span>"
        "</div></header>"
    )
    panels = "".join(
        _sheet_html(sheet, index, several, language, stored[index] if index < len(stored) else None)
        for index, sheet in enumerate(sheets)
    )
    if not sheets:
        panels = (
            '<section class="sx-sheet"><div class="sx-scroll">'
            f'<div class="sx-empty">{_ICON_EMPTY}<p>No rows yet</p></div></div></section>'
        )
    tabs = ""
    if several:
        buttons = "".join(
            f'<button type="button" role="tab" id="sx-tab-{index}" '
            f'aria-controls="sx-sheet-{index}" aria-selected="{"false" if index else "true"}" '
            f'tabindex="{-1 if index else 0}">'
            f'<span class="sx-tn"{_name_mark(stored, index, sheet)}>{esc(sheet["name"])}</span>'
            "</button>"
            for index, sheet in enumerate(sheets)
        )
        tabs = f'<div class="sx-tabs" role="tablist" aria-label="Sheets">{buttons}</div>'
    body = f'{_SYMBOLS}<div class="sx">{head}<main class="sx-main">{panels}</main>{tabs}</div>'
    return document(node, body=body, css=_PAGE_CSS, js=_PAGE_JS, body_class="fill", kit_js=False)


# -------------------------------------------------------------------- preview


def _preview_text(value: Any, kind: str, decimals: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "✓" if value else ""
    if _is_number(value):
        if kind not in _NUMERIC:
            return _raw(value)
        text = f"{float(value):.{decimals}f}"
        return f"{text}%" if kind == "percent" else text
    if isinstance(value, dict):
        href = str(value.get("href") or "")
        return _link_label(str(value.get("text") or ""), href) if href else _text_of(value)
    return _text_of(value)


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on the node's card: the first sheet's top-left corner."""
    empty: dict[str, Any] = {"columns": [], "rows": [], "numeric": [], "count": 0}
    sheets = spec.get("sheets") if isinstance(spec, dict) else None
    sheet = sheets[0] if isinstance(sheets, list) and sheets else None
    if not isinstance(sheet, dict):
        return empty
    raw_columns = [c for c in as_list(sheet.get("columns"), MAX_COLUMNS) if isinstance(c, dict)]
    all_rows = [r for r in as_list(sheet.get("rows"), MAX_ROWS) if isinstance(r, dict)]
    try:
        order = _formula_order(raw_columns, str(sheet.get("name") or ""))
    except NodeError:  # a spec that was never normalized: its formula cells stay empty
        order = []
    shown = _filled(all_rows[:3], order)
    columns: list[str] = []
    numeric: list[bool] = []
    cells: list[list[str]] = [[] for _ in shown]
    for raw in raw_columns[:3]:
        key = str(raw.get("key") or "")
        kind = _kind(raw, all_rows)
        values = [float(row[key]) for row in shown if _is_number(row.get(key))]
        decimals = _decimals(raw, kind, values) if kind in _NUMERIC else 0
        columns.append(clean(raw.get("label") or key, 24))
        numeric.append(kind in _NUMERIC)
        for line, row in zip(cells, shown, strict=True):
            line.append(clean(_preview_text(row.get(key), kind, decimals), 24))
    return {"columns": columns, "rows": cells, "numeric": numeric, "count": len(all_rows)}


# ------------------------------------------------------------ starter and guide


def starter(title: str, language: str) -> dict[str, Any]:
    """A fresh sheet: a text, a number and a status column with three rows to replace."""
    del title, language  # the page already carries the title; the words here are few
    return normalize(
        {
            "sheets": [
                {
                    "name": "Sheet 1",
                    "columns": [
                        {"key": "item", "label": "Item", "type": "text"},
                        {"key": "amount", "label": "Amount", "type": "number", "total": "sum"},
                        {"key": "status", "label": "Status", "type": "status"},
                    ],
                    "rows": [
                        {"item": "First item", "amount": 120, "status": "Open"},
                        {"item": "Second item", "amount": 80, "status": "Draft"},
                        {"item": "Third item", "amount": 45, "status": "Done"},
                    ],
                    "freeze": 1,
                }
            ]
        }
    )


EXAMPLE: Final[dict[str, Any]] = {
    "note": "Office supplies, March",
    "sheets": [
        {
            "name": "Orders",
            "columns": [
                {"key": "item", "label": "Item"},
                {"key": "qty", "label": "Qty", "type": "number"},
                {"key": "price", "label": "Price", "type": "currency", "unit": "EUR"},
                {
                    "key": "amount",
                    "label": "Amount",
                    "type": "currency",
                    "unit": "EUR",
                    "formula": "qty * price",
                    "total": "sum",
                },
            ],
            "rows": [
                {"item": "Paper", "qty": 4, "price": 5.5},
                {"item": "Toner", "qty": 2, "price": 39},
            ],
        }
    ],
}

GUIDE: Final[str] = (
    'Node type "sheets": a spreadsheet the person reads, sorts and filters (read-only).\n'
    "\n"
    'spec = {"sheets": [sheet, ...] (1-12), "note": one line under the title (optional)}\n'
    'Shorthand: top-level "columns" + "rows" is one sheet.\n'
    'sheet = {"name": str, "columns": [column, ...] (1-30), "rows": [row, ...] (up to 1000), '
    '"freeze": 0-3 leading columns that stay in view (default 1)}\n'
    'column = {"key": id used in rows and formulas (default: the label in lower case with _ '
    'for other characters), "label": str, "type": "text" | "number" | "currency" | "percent" '
    '| "date" | "check" | "status" | "link" (default: inferred from the rows), "unit": e.g. '
    '"kg", for currency a code such as "EUR", "decimals": 0-4, "total": "sum" | "avg" | '
    '"min" | "max" | "count" (a pinned bottom row), "formula": str}. A plain string is a '
    "column with that label.\n"
    "row = an object keyed by column key, or a list of cells in column order (null for a "
    "formula column). A cell is text, a number, true/false or null.\n"
    "\n"
    "- Send numbers as numbers, never as formatted text: the page writes them in the "
    "reader's locale. percent: 12.5 means 12.5 %.\n"
    '- date: ISO, "2026-03-31" or "2026-03-31T14:30".\n'
    "- status: a short word shown as a chip. done/paid/delivered/ok read as good, "
    "pending/open/in progress as info, late/overdue/blocked/failed as bad, anything else "
    'neutral. For other words and other languages give the tone: {"text": "...", "tone": '
    '"good" | "info" | "warn" | "bad"}.\n'
    '- link: {"text": "...", "href": "https://..."} or a bare URL.\n'
    '- formula: arithmetic over the row\'s other columns by key, e.g. "qty * price" or '
    '"round(revenue / visits * 100, 1)". Allowed: numbers, column keys, + - * / // % **, '
    "parentheses, round, min, max, abs, sum. Do not send cells for a formula column; a "
    "missing input or a division by zero leaves the cell empty.\n"
    '- Put the column that names the row first. No total rows inside "rows": use "total". '
    "Short labels.\n"
    "\n"
    "Example:\n" + json.dumps(EXAMPLE, ensure_ascii=False)
)


__all__ = [
    "COLUMN_TYPES",
    "EXAMPLE",
    "GUIDE",
    "MAX_COLUMNS",
    "MAX_ROWS",
    "MAX_SHEETS",
    "TONES",
    "TOTALS",
    "evaluate",
    "evaluate_formula",
    "normalize",
    "parse_formula",
    "preview",
    "render",
    "starter",
]
