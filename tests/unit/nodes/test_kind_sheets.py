"""The sheets node type: its grammar, its formulas and its page."""

from __future__ import annotations

import copy
import json
import re
from html import escape
from typing import Any

import pytest

from dodaios.artifacts.design_guide import PAGE_JS
from dodaios.nodes.kinds import sheets
from dodaios.nodes.kinds.sheets import (
    EXAMPLE,
    GUIDE,
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_SHEETS,
    evaluate_formula,
    normalize,
    parse_formula,
    preview,
    render,
    starter,
)
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError
from tests.unit.nodes.editable import Field, check_editable, editable_fields

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'


def _node(spec: Any, *, title: str = "Accounts", normalized: bool = True, **fields: Any) -> Node:
    return Node(
        id="0123456789ab",
        type="sheets",
        title=title,
        spec=normalize(spec) if normalized else spec,
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_600,
        **fields,
    )


def _orders() -> dict[str, Any]:
    return {
        "sheets": [
            {
                "name": "Orders",
                "columns": [
                    {"key": "item", "label": "Item"},
                    {"key": "qty", "label": "Qty", "type": "number", "total": "sum"},
                    {"key": "price", "label": "Price", "type": "currency", "unit": "EUR"},
                    {
                        "key": "amount",
                        "label": "Amount",
                        "type": "currency",
                        "unit": "EUR",
                        "formula": "qty * price",
                        "total": "sum",
                    },
                    {"key": "state", "label": "State", "type": "status", "total": "count"},
                ],
                "rows": [
                    {"item": "Paper", "qty": 4, "price": 5.5, "state": "Paid"},
                    {"item": "Toner", "qty": 2, "price": 39, "state": "Overdue"},
                    {"item": "Desk", "qty": 1, "state": "Draft"},
                ],
            }
        ]
    }


#: The marks of the edit mode (`nodes/bridge.py`). A value's source rides in
#: ``data-src`` as an escaped attribute: data, never drawn.
_EDIT_MARKS = re.compile(r' data-(?:at|src|as)="[^"]*"| data-refresh\b')


def _view(html: str) -> str:
    """The page as view mode draws it: without the marks of the edit mode."""
    return _EDIT_MARKS.sub("", html)


def _cells(html: str) -> list[str]:
    """The body cells of the first grid, as raw HTML."""
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return re.findall(r"<td[^>]*>.*?</td>", body)


# ---------------------------------------------------------------- normalize


def test_normalize_is_idempotent_and_survives_a_json_round_trip() -> None:
    messy = {
        "sheets": [
            {
                "name": "  Orders   2026 ",
                "columns": [
                    "Item",
                    {"label": "Unit Price", "type": "money", "unit": "EUR", "decimals": 9},
                    {"key": "Qty", "type": "INT", "total": "SUM", "colour": "red"},
                    {"label": "Amount", "formula": "= Qty * Unit_Price", "total": "sum"},
                    {"label": "2026", "type": "percent"},
                    {"label": "Class"},
                    {"label": "Item"},
                ],
                "rows": [
                    {"ITEM": " Paper ", "unit price": "5.50", "qty": 4, "amount": 999, "x": 1},
                    ["Toner", 39, 2, None, 12.5, "A", "again"],
                    {},
                    "not a row",
                ],
                "freeze": 9,
                "zoom": 2,
            }
        ],
        "note": "  first   quarter ",
        "theme": "dark",
    }
    once = normalize(messy)
    assert normalize(once) == once
    assert normalize(json.loads(json.dumps(once))) == once

    sheet = once["sheets"][0]
    assert once["note"] == "first quarter" and "theme" not in once
    assert sheet["name"] == "Orders 2026" and sheet["freeze"] == 3 and "zoom" not in sheet
    assert [c["key"] for c in sheet["columns"]] == [
        "item",
        "unit_price",
        "qty",
        "amount",
        "_2026",
        "class_",
        "item_2",
    ]
    price, qty, amount = sheet["columns"][1:4]
    assert price == {
        "key": "unit_price",
        "label": "Unit Price",
        "type": "currency",
        "unit": "EUR",
        "decimals": 4,
    }
    assert qty == {"key": "qty", "label": "Qty", "type": "number", "total": "sum"}
    assert amount["formula"] == "qty * unit_price" and "type" not in amount
    # A formula column never stores cells; an empty row and a non-row are dropped.
    assert sheet["rows"] == [
        {"item": "Paper", "unit_price": 5.5, "qty": 4},
        {"item": "Toner", "unit_price": 39, "qty": 2, "_2026": 12.5, "class_": "A",
         "item_2": "again"},
    ]


def test_normalize_bounds_sheets_columns_rows_and_texts() -> None:
    wide = {"columns": [f"C{i}" for i in range(50)], "rows": [[i] for i in range(MAX_ROWS + 50)]}
    spec = normalize({"sheets": [dict(wide, name="n" * 200) for _ in range(20)], "note": "x" * 900})

    assert len(spec["sheets"]) == MAX_SHEETS
    sheet = spec["sheets"][0]
    assert len(sheet["columns"]) == MAX_COLUMNS and len(sheet["rows"]) == MAX_ROWS
    assert len(sheet["name"]) == 40 and len(spec["note"]) == 200

    clipped = normalize({"columns": ["L" * 300], "rows": [["t" * 2_000]]})["sheets"][0]
    assert len(clipped["columns"][0]["label"]) == 60
    assert len(clipped["columns"][0]["key"]) <= 40
    assert len(clipped["rows"][0][clipped["columns"][0]["key"]]) == 500


def test_the_shorthand_is_one_sheet_and_row_keys_can_stand_in_for_columns() -> None:
    short = normalize({"columns": ["Name", "Age"], "rows": [["Ada", 36]], "note": "n"})
    assert short == {
        "sheets": [
            {
                "name": "Sheet 1",
                "columns": [{"key": "name", "label": "Name"}, {"key": "age", "label": "Age"}],
                "rows": [{"name": "Ada", "age": 36}],
                "freeze": 1,
            }
        ],
        "note": "n",
    }
    derived = normalize({"rows": [{"City": "Oslo", "Pop": 700_000}, {"City": "Rome"}]})
    assert [c["label"] for c in derived["sheets"][0]["columns"]] == ["City", "Pop"]
    assert derived["sheets"][0]["rows"][1] == {"city": "Rome"}


@pytest.mark.parametrize(
    "spec",
    [
        None,
        [],
        "a table",
        {},
        {"sheets": []},
        {"sheets": ["Orders"]},
        {"sheets": [{"name": "Orders", "rows": [[1, 2]]}]},
        {"sheets": [{"columns": ["A"], "rows": "none"}]},
    ],
)
def test_an_unusable_spec_is_refused_with_one_sentence(spec: Any) -> None:
    with pytest.raises(NodeError) as caught:
        normalize(spec)
    message = str(caught.value)
    assert message.endswith(".") and "\n" not in message and len(message) < 260


def test_column_types_are_inferred_from_the_rows_and_never_frozen() -> None:
    spec = normalize(
        {
            "columns": ["Name", "Score", "Member", "Mixed", "Empty"],
            "rows": [["Ada", 3, True, 1, None], ["Bo", 4.5, False, "one", None]],
        }
    )
    sheet = spec["sheets"][0]
    assert all("type" not in column for column in sheet["columns"])
    columns, _rows = sheets._read(sheet)
    assert [c.kind for c in columns] == ["text", "number", "check", "text", "text"]

    # A sheet that starts empty takes its types from the rows it gets later.
    later = normalize({"columns": ["Name", "Score"], "rows": []})
    later["sheets"][0]["rows"] = [{"name": "Ada", "score": 3}]
    columns, _rows = sheets._read(normalize(later)["sheets"][0])
    assert [c.kind for c in columns] == ["text", "number"]


def test_rows_as_objects_and_as_lists_give_the_same_sheet() -> None:
    columns = [
        {"key": "name", "label": "Full name"},
        {"key": "paid", "label": "Paid", "type": "check"},
        {"key": "due", "label": "Due", "type": "number"},
    ]
    by_key = normalize({"columns": columns, "rows": [{"name": "Ada", "paid": "yes", "due": "12"}]})
    by_label = normalize(
        {"columns": columns, "rows": [{"FULL NAME": "Ada", "Paid": True, "DUE": 12}]}
    )
    by_list = normalize({"columns": columns, "rows": [["Ada", 1, 12.0, "one cell too many"]]})

    assert by_key["sheets"][0]["rows"] == [{"name": "Ada", "paid": True, "due": 12}]
    assert by_key == by_label == by_list


def test_cells_keep_their_type_and_drop_what_is_not_a_value() -> None:
    spec = normalize(
        {
            "columns": [
                {"key": "n", "label": "N", "type": "number"},
                {"key": "c", "label": "C", "type": "check"},
                {"key": "s", "label": "S", "type": "status"},
                {"key": "l", "label": "L", "type": "link"},
                {"key": "d", "label": "D", "type": "date"},
            ],
            "rows": [
                {"n": "n/a", "c": "no", "s": {"text": "Bezahlt", "tone": "good"},
                 "l": "https://example.org/a", "d": "2026-03-31"},
                {"n": float("inf"), "c": "maybe", "s": {"text": "Odd", "tone": "pink"},
                 "l": {"text": "Site", "href": "javascript:alert(1)"}, "d": 20260331},
                {"n": True, "c": 0, "s": "", "l": {"text": "Doc", "url": "http://example.org"}},
            ],
        }
    )
    assert spec["sheets"][0]["rows"] == [
        {
            "n": "n/a",
            "c": False,
            "s": {"text": "Bezahlt", "tone": "good"},
            "l": {"text": "https://example.org/a", "href": "https://example.org/a"},
            "d": "2026-03-31",
        },
        {"s": "Odd", "l": "Site", "d": "20260331"},
        {"c": False, "l": {"text": "Doc", "href": "http://example.org"}},
    ]


# ------------------------------------------------------------------ formulas


def test_formula_precedence_and_functions() -> None:
    row = {"a": 2, "b": 3, "c": 4.5}
    assert evaluate_formula("a + b * c", row) == 15.5
    assert evaluate_formula("(a + b) * c", row) == 22.5
    assert evaluate_formula("-a ** 2", row) == -4
    assert evaluate_formula("2 ** 3 ** 2", {}) == 512
    assert evaluate_formula("7 // 2 + 7 % 2", {}) == 4
    assert evaluate_formula("round(c)", row) == 5  # half away from zero, as a sheet rounds
    assert evaluate_formula("round(2.675, 2)", {}) == 2.68
    assert evaluate_formula("round(1234.5, -2)", {}) == 1200
    assert evaluate_formula("min(a, b, c) + max(a, b, c)", row) == 6.5
    assert evaluate_formula("abs(a - b) + sum(a, b, c)", row) == 10.5
    assert evaluate_formula("0.1 + 0.2", {}) == 0.3


def test_a_formula_without_its_inputs_is_an_empty_cell_never_an_error() -> None:
    assert evaluate_formula("a / b", {"a": 1, "b": 0}) is None
    assert evaluate_formula("a // b", {"a": 1, "b": 0}) is None
    assert evaluate_formula("a % b", {"a": 1, "b": 0}) is None
    assert evaluate_formula("a * 2", {}) is None
    assert evaluate_formula("a * 2", {"a": None}) is None
    assert evaluate_formula("a * 2", {"a": "12"}) is None
    assert evaluate_formula("a * 2", {"a": True}) is None
    assert evaluate_formula("2 ** 4000", {}) is None
    assert evaluate_formula("a ** 60", {"a": 1e300}) is None
    assert evaluate_formula("(0 - 8) ** 0.5", {}) is None
    assert evaluate_formula("round(a, 400)", {"a": 1.5}) == 1.5


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "__import__('os').system('true')",
        "a.real",
        "a[0]",
        "[a for a in (1, 2)]",
        "lambda: 1",
        "a if b else 1",
        "a and b",
        "a < b",
        "'text' * 3",
        "True + 1",
        "1j * 2",
        "1e999",
        "eval('1')",
        "pow(2, 3)",
        "round()",
        "round(a, b, 3)",
        "abs(a, b)",
        "max(*a)",
        "round(a, ndigits=1)",
        "a; b",
        "a = 1",
        "(a := 1)",
        "f'{a}'",
        "",
        "((((",
        "1 + " * 200 + "1",
    ],
)
def test_anything_outside_the_formula_grammar_is_refused(expression: str) -> None:
    with pytest.raises(NodeError):
        parse_formula(expression, "Total")


def test_a_refused_formula_names_its_column_at_normalize_time() -> None:
    def spec(formula: str) -> dict[str, Any]:
        return {"columns": ["Qty", {"label": "Line total", "formula": formula}], "rows": [[1]]}

    for formula in ("__import__('os')", "qty.real", "qty * price", "line_total + 1"):
        with pytest.raises(NodeError, match="Column 'Line total'"):
            normalize(spec(formula))

    loop = {
        "columns": [
            {"key": "a", "label": "A", "formula": "b + 1"},
            {"key": "b", "label": "B", "formula": "a + 1"},
        ],
        "rows": [],
    }
    with pytest.raises(NodeError, match="depends on itself"):
        normalize(loop)


def test_formula_columns_are_computed_in_python_and_may_build_on_each_other() -> None:
    spec = normalize(
        {
            "columns": [
                {"key": "gross", "label": "Gross", "formula": "net + tax"},
                {"key": "net", "label": "Net", "type": "number"},
                {"key": "rate", "label": "Rate", "type": "percent"},
                {"key": "tax", "label": "Tax", "formula": "round(net * rate / 100, 2)"},
            ],
            "rows": [{"net": 100, "rate": 19}, {"net": 50}, {"rate": 7, "gross": 1}],
        }
    )
    columns, rows = sheets._read(spec["sheets"][0])

    assert [c.kind for c in columns] == ["number", "number", "percent", "number"]
    assert rows[0] == {"net": 100, "rate": 19, "tax": 19.0, "gross": 119.0}
    assert rows[1] == {"net": 50}  # no rate: tax and gross stay empty
    assert rows[2] == {"rate": 7}

    html = render(_node(spec))
    first = _cells(html)[:5]
    assert 'data-value="119"' in first[1] and ">119<" in first[1]
    assert 'title="= round(net * rate / 100, 2)"' in html


# -------------------------------------------------------------------- render


def test_numbers_ship_their_raw_value_and_a_fallback_in_the_page_language() -> None:
    spec = {
        "columns": [
            {"key": "net", "label": "Net", "type": "currency", "unit": "EUR"},
            {"key": "share", "label": "Share", "type": "percent"},
            {"key": "load", "label": "Load", "type": "number", "unit": "kg", "decimals": 1},
            {"key": "yen", "label": "Yen", "type": "currency", "unit": "¥"},
        ],
        "rows": [[1234.5, 12.5, -3, 1500], [7, 40, 2.25, 20]],
    }
    english = _view(render(_node(spec, language="en")))
    german = _view(render(_node(spec, language="de-DE")))

    assert '<td class="n f1" tabindex="0" data-value="1234.5">1,234.50' in english
    assert '<span class="u"> EUR</span>' in english
    assert 'data-value="12.5">12.5%</td>' in english
    assert 'data-value="-3">−3.0<span class="u"> kg</span>' in english
    assert 'data-value="1234.5">1.234,50' in german
    assert 'data-value="12.5">12,5 %</td>' in german
    # What the page script formats with: the type, the currency code, the decimals.
    assert 'data-t="currency" data-u="EUR" data-d="2"' in english
    assert 'data-t="percent" data-u="" data-d="1"' in english
    assert 'data-t="number" data-u="kg" data-d="1"' in english
    assert 'data-t="currency" data-u="JPY" data-d="0"' in english
    assert "Intl.NumberFormat" in english and "navigator.language" in english


def test_totals_are_precomputed_and_marked_for_the_page_script() -> None:
    html = render(_node(_orders()))
    foot = html.split("<tfoot>", 1)[1].split("</tfoot>", 1)[0]
    totals = re.findall(r'<span class="tv">(.*?)</span></span></td>', foot)

    # qty 4 + 2 + 1; amount 22 + 78 (the row without a price has no amount); three states.
    assert totals == ["7", '100.00<span class="u"> EUR</span>', "3"]
    assert html.count('data-total="sum"') == 2 and html.count('data-total="count"') == 1
    assert foot.count("<td") == 7  # the gutter, five columns, the filler

    assert sheets._total("avg", [1.0, 2.0, 6.0], 3) == 3.0
    assert sheets._total("min", [4.0, -1.0], 2) == -1.0
    assert sheets._total("max", [4.0, -1.0], 2) == 4.0
    assert sheets._total("sum", [0.1, 0.2, 0.3], 3) == pytest.approx(0.6)
    assert sheets._total("count", [], 5) == 5.0
    assert sheets._total("sum", [], 0) is None


def test_a_total_that_means_nothing_for_the_column_is_left_out() -> None:
    spec = {
        "columns": [{"label": "Name", "total": "sum"}, {"label": "Done", "type": "check",
                                                         "total": "count"}],
        "rows": [["Ada", True], ["Bo", False], ["Cy", True]],
    }
    html = render(_node(spec))
    assert 'data-total="sum"' not in html
    foot = html.split("<tfoot>", 1)[1]
    assert '<span class="tv">2</span>' in foot  # a check column counts its checked rows


def test_status_tones_come_from_the_word_or_from_the_spec() -> None:
    words = ["Done", "paid", "DELIVERED", "ok", "Pending", "open", "In progress", "late",
             "Overdue", "blocked", "failed", "Draft", "unknown", "Verschickt"]
    tones = [sheets._status_tone(word)[1] for word in words]
    assert tones == ["good"] * 4 + ["info"] * 3 + ["bad"] * 4 + [""] * 3
    assert sheets._status_tone({"text": "Draft", "tone": "warn"}) == ("Draft", "warn")

    spec = {
        "columns": [{"label": "State", "type": "status"}],
        "rows": [["Paid"], ["Draft"], [{"text": "Verschickt", "tone": "info"}],
                 [{"text": "Risky", "tone": "warn"}], ["Overdue"]],
    }
    html = render(_node(spec))
    assert '<span class="chip good">Paid</span>' in html
    assert '<span class="chip">Draft</span>' in html
    assert '<span class="chip info">Verschickt</span>' in html
    assert '<span class="chip warn">Risky</span>' in html
    assert '<span class="chip bad">Overdue</span>' in html


def test_dates_checks_and_links_are_drawn_as_what_they_are() -> None:
    spec = {
        "columns": [
            {"key": "day", "label": "Day", "type": "date"},
            {"key": "ok", "label": "OK", "type": "check"},
            {"key": "src", "label": "Source", "type": "link"},
        ],
        "rows": [
            ["2026-03-31", True, {"text": "Invoice", "href": "https://example.org/i?a=1&b=2"}],
            ["2026-03-31 14:30:10", False, "https://www.example.org/path/"],
            ["end of March", None, "ftp://example.org/file"],
            ["2026-02-30", True, "mailto:ada@example.org"],
        ],
        "freeze": 0,
    }
    html = _view(render(_node(spec)))

    assert 'data-value="2026-03-31">2026-03-31</td>' in html
    assert 'data-value="2026-03-31T14:30">2026-03-31 14:30:10</td>' in html
    assert "<td>end of March</td>" in html and "<td>2026-02-30</td>" in html
    assert html.count('<use href="#sx-ck"/>') == 2 and html.count('class="ck off"') == 1
    assert 'href="https://example.org/i?a=1&amp;b=2"' in html and ">Invoice</a>" in html
    assert ">example.org/path</a>" in html and ">ada@example.org</a>" in html
    assert "ftp://example.org/file</td>" in html and 'href="ftp:' not in html


def test_the_page_is_a_grid_that_fills_the_window() -> None:
    html = render(_node(_orders()))

    assert '<body class="fill">' in html
    assert '<meta name="dodaios-node-type" content="sheets">' in html
    assert 'role="grid"' in html and 'aria-readonly="true"' in html
    assert 'type="search"' in html and "<span data-count>3</span>" in html
    assert html.count('aria-sort="none"') == 5
    assert 'data-freeze="1" data-fz="1"' in html
    # One sheet needs no tabs; the kit's own table script is left out for the grid's.
    assert 'role="tablist"' not in html
    assert PAGE_JS not in html
    assert "dodaios-open-link" in html
    assert "@media print" in html


def test_several_sheets_get_tabs_and_only_the_first_is_shown() -> None:
    spec = {
        "sheets": [
            {"name": "Plan", "columns": ["A"], "rows": [[1]], "freeze": 0},
            {"name": "Actual", "columns": ["A", "B", "C", "D"], "rows": [[1, 2, 3, 4]],
             "freeze": 3},
            {"name": "Later", "columns": ["A"], "rows": []},
        ]
    }
    html = _view(render(_node(spec)))

    assert html.count('<button type="button" role="tab"') == 3
    assert html.count('role="tabpanel"') == 3
    assert 'aria-selected="true" tabindex="0"><span class="sx-tn">Plan</span></button>' in html
    assert 'aria-selected="false" tabindex="-1"><span class="sx-tn">Actual</span></button>' in html
    assert '<section class="sx-sheet" id="sx-sheet-0"' in html
    assert '<section class="sx-sheet is-off" id="sx-sheet-1"' in html
    assert 'data-freeze="0"' in html and 'data-freeze="3"' in html
    assert '<h2 class="sx-name">Actual</h2>' in html  # the sheet's name in print
    assert html.count("No rows yet") == 1 and html.count("<tfoot>") == 0


def test_an_empty_sheet_and_an_unreadable_spec_still_give_a_page() -> None:
    empty = render(_node({"columns": ["Date", {"label": "Net", "total": "sum"}], "rows": []}))
    assert "No rows yet" in empty and "<tfoot>" not in empty
    assert "<span data-count>0</span>" in empty
    assert '<th scope="col" class="f1" data-t="text" tabindex="0"' in empty

    broken = render(_node({"sheets": "nothing"}, normalized=False))
    assert "No rows yet" in broken and "<table" not in broken


def test_no_text_from_the_spec_reaches_the_page_unescaped() -> None:
    for payload in (SCRIPT, BREAKOUT):
        spec = {
            "note": payload,
            "sheets": [
                {
                    "name": payload,
                    "columns": [
                        {"key": payload, "label": payload, "unit": payload},
                        {"key": "n", "label": payload, "type": "number", "unit": payload,
                         "total": "sum"},
                        {"key": "c", "label": payload, "type": "currency", "unit": payload},
                        {"key": "p", "label": "P", "type": "percent", "unit": payload},
                        {"key": "d", "label": "D", "type": "date"},
                        {"key": "s", "label": "S", "type": "status"},
                        {"key": "l", "label": "L", "type": "link"},
                        {"key": "k", "label": "K", "type": "check"},
                        {"key": "f", "label": payload, "formula": "n * 2", "unit": payload},
                    ],
                    "rows": [
                        [payload, 1, 2, 3, payload, payload, payload, payload],
                        [payload * 20, payload, payload, payload, "2026-01-01",
                         {"text": payload, "tone": "good"},
                         {"text": payload, "href": "https://example.org/" + payload}, True],
                        {"l": {"text": payload, "href": "javascript:" + payload}},
                    ],
                },
                {"name": payload, "columns": [payload], "rows": []},
            ],
        }
        html = render(_node(spec, title=payload, track="watch", note=payload))

        assert payload not in html
        assert "<img" not in html and "alert(1)</script>" not in html
        assert 'href="javascript:' not in html
        # The page's own scripts are the only ones: the theme, the clock, the grid.
        assert html.count("<script>") == 4 and html.count("</script>") == 4


def test_render_is_deterministic_and_does_not_touch_the_spec() -> None:
    spec = normalize(_orders())
    before = copy.deepcopy(spec)
    node = _node(spec)

    assert render(node) == render(_node(copy.deepcopy(spec)))
    assert node.spec == before


def test_the_page_reaches_nothing_outside_itself() -> None:
    html = render(_node(_orders(), track="watch"))
    # (`data-src` is the edit mode's copy of a value, not an address.)
    assert not re.search(r'(?<![\w-])(?:src|href)="(?!#)', html)
    assert "url(" not in html and "@import" not in html
    for banned in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "clipboard",
                   "document.cookie", "window.open"):
        assert banned not in html
    # Colours come from the tokens: the type's own styles name no colour of their own.
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", sheets._PAGE_CSS)


def test_a_kept_current_sheet_shows_when_it_was_last_refreshed() -> None:
    plain = render(_node(_orders()))
    assert "data-updated" not in plain and 'class="node-meta"' not in plain

    kept = render(_node(_orders(), track="Invoices in the mailbox", note="Mailbox offline"))
    assert '<p class="node-meta"><span class="live">' in kept
    assert '<time data-updated="1700000600"></time>' in kept
    assert '<p class="node-note">Mailbox offline</p>' in kept
    assert "Intl.RelativeTimeFormat" in kept

    running = render(_node(_orders(), track="Invoices", refreshing=True))
    assert '<span class="live on">' in running


def test_the_note_stands_under_the_title() -> None:
    html = _view(render(_node(dict(_orders(), note="Office supplies, March"), title="Orders 2026")))
    assert "<title>Orders 2026</title>" in html
    assert "<h1>Orders 2026</h1>" in html
    assert '<p class="sx-note">Office supplies, March</p>' in html


# ----------------------------------------------------------------- edit mode


def _with_empty_cells(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec with every empty cell present as ``None``.

    An empty cell is missing from its stored row (saving it creates the key),
    so ``check_editable`` checks it against ``None``: offered as nothing.
    """
    full = copy.deepcopy(spec)
    for sheet in full["sheets"]:
        keys = [c["key"] for c in sheet["columns"] if "formula" not in c]
        for row in sheet["rows"]:
            for key in keys:
                row.setdefault(key, None)
    return full


def _fields(node: Node) -> dict[str, Field]:
    """What the page offers to edit, checked against the stored spec."""
    page = render(node)
    fields = check_editable(page, _with_empty_cells(node.spec), node.title)
    paths = [field.at for field in fields]
    assert len(paths) == len(set(paths)), "a value is offered twice"
    return {field.at: field for field in fields}


def _every_value(spec: dict[str, Any]) -> set[str]:
    """The places a reader may write into: every stored cell outside a formula
    column (empty or not), every label, the names when there are tabs, the note."""
    paths = {"@title"}
    if spec.get("note"):
        paths.add("/note")
    several = len(spec["sheets"]) > 1
    for s, sheet in enumerate(spec["sheets"]):
        if several:
            paths.add(f"/sheets/{s}/name")
        for c, column in enumerate(sheet["columns"]):
            paths.add(f"/sheets/{s}/columns/{c}/label")
            if "formula" in column:
                continue
            for r, row in enumerate(sheet["rows"]):
                cell = row.get(column["key"])
                inner = "/text" if isinstance(cell, dict) else ""
                paths.add(f"/sheets/{s}/rows/{r}/{column['key']}{inner}")
    return paths


def _every_type() -> dict[str, Any]:
    return {
        "note": "Two sheets, every type",
        "sheets": [
            {
                "name": "All",
                "columns": [
                    {"key": "name", "label": "Name", "type": "text"},
                    {"key": "qty", "label": "Qty", "type": "number", "unit": "kg"},
                    {"key": "net", "label": "Net", "type": "currency", "unit": "EUR"},
                    {"key": "share", "label": "Share", "type": "percent"},
                    {"key": "day", "label": "Day", "type": "date"},
                    {"key": "ok", "label": "OK", "type": "check"},
                    {"key": "state", "label": "State", "type": "status"},
                    {"key": "src", "label": "Source", "type": "link"},
                    {"key": "free", "label": "Free"},
                ],
                "rows": [
                    ["Ada", 4, 1234.5, 12.5, "2026-03-31", True, "Paid",
                     {"text": "Invoice", "href": "https://example.org/i"}, 7],
                    ["Bo", "n/a", None, None, "end of March", False,
                     {"text": "Risky", "tone": "warn"}, "https://www.example.org/", "x"],
                    {"name": "Cy", "free": True},
                    {"qty": 1.25, "src": "a note, no address"},
                ],
            },
            {"name": "Later", "columns": ["A", {"label": "B", "type": "number"}], "rows": []},
        ],
    }


@pytest.mark.parametrize(
    "spec",
    [EXAMPLE, starter("Budget", "en"), _every_type(), _orders()],
    ids=["example", "starter", "every-type", "orders"],
)
def test_every_value_the_page_draws_can_be_edited_where_the_spec_holds_it(
    spec: dict[str, Any],
) -> None:
    node = _node(spec, note="Kept", track="watch")
    assert set(_fields(node)) == _every_value(node.spec)


def test_a_small_sheet_offers_exactly_its_values() -> None:
    node = _node(
        {
            "columns": [{"key": "item", "label": "Item"}, {"key": "qty", "label": "Qty"},
                        {"key": "twice", "label": "Twice", "formula": "qty * 2"}],
            "rows": [{"item": "Paper", "qty": 4}, {"item": "Toner"}],
        },
        title="Stock",
    )
    fields = _fields(node)

    # Rows are objects keyed by column key; a row's place is its stored index.
    assert set(fields) == {
        "@title",
        "/sheets/0/columns/0/label",
        "/sheets/0/columns/1/label",
        "/sheets/0/columns/2/label",
        "/sheets/0/rows/0/item",
        "/sheets/0/rows/0/qty",
        "/sheets/0/rows/1/item",
        "/sheets/0/rows/1/qty",
    }
    assert fields["@title"].text == "Stock"
    assert fields["/sheets/0/columns/2/label"].text == "Twice"
    # The empty cell is offered as an empty number, and is missing from its stored row.
    empty = fields["/sheets/0/rows/1/qty"]
    assert (empty.kind, empty.src, empty.text) == ("number", "", "")
    assert "qty" not in node.spec["sheets"][0]["rows"][1]
    # The formula column's cells are computed: nothing there is offered.
    assert not any("twice" in path for path in fields)
    assert "8</td>" in render(node)


def test_cells_are_offered_as_what_they_hold() -> None:
    node = _node(_every_type())
    fields = _fields(node)
    row = "/sheets/0/rows/"

    # Numbers as numbers, with the stored value written plainly.
    assert (fields[row + "0/qty"].kind, fields[row + "0/qty"].src) == ("number", "4")
    assert (fields[row + "0/net"].kind, fields[row + "0/net"].src) == ("number", "1234.5")
    assert fields[row + "0/net"].text == "1,234.50 EUR"
    assert (fields[row + "0/share"].src, fields[row + "0/share"].text) == ("12.5", "12.5%")
    assert (fields[row + "3/qty"].kind, fields[row + "3/qty"].src) == ("number", "1.25")
    assert (fields[row + "0/free"].kind, fields[row + "0/free"].src) == ("number", "7")
    assert (fields[row + "1/net"].kind, fields[row + "1/net"].src) == ("number", "")
    # Text in a number column stays text: what is typed there may become a number.
    assert (fields[row + "1/qty"].kind, fields[row + "1/qty"].text) == ("text", "n/a")
    # Checks are toggles, an empty check is an unchecked one.
    assert (fields[row + "0/ok"].kind, fields[row + "0/ok"].src) == ("toggle", "true")
    assert (fields[row + "1/ok"].src, fields[row + "2/ok"].src) == ("false", "false")
    assert (fields[row + "2/free"].kind, fields[row + "2/free"].src) == ("toggle", "true")
    # A date is edited as stored; the page writes it out in the reader's locale.
    assert fields[row + "0/day"].src == "2026-03-31"
    assert fields[row + "1/day"].src == "end of March"
    # A status word, a chip's text (its tone stays), a link's text (its address stays).
    assert fields[row + "0/state"].text == "Paid" and fields[row + "0/state"].src is None
    assert fields[row + "1/state/text"].text == "Risky"
    assert fields[row + "0/src/text"].src == "Invoice"
    assert fields[row + "1/src/text"].src == "https://www.example.org/"
    assert fields[row + "1/src/text"].text == "example.org"
    assert fields[row + "3/src"].text == "a note, no address"
    # Empty cells are offered too: text, number, status, link.
    assert fields[row + "2/qty"].kind == "number" and fields[row + "2/state"].text == ""
    assert fields[row + "3/name"].text == "" and fields[row + "2/src"].text == ""
    # Labels, the names on the tabs, the note, the title. No field is multi-line.
    assert fields["/sheets/1/columns/1/label"].text == "B"
    assert fields["/sheets/0/name"].text == "All" and fields["/sheets/1/name"].text == "Later"
    assert fields["/note"].text == "Two sheets, every type"
    assert not any(field.multiline for field in fields.values())


def test_a_sheet_with_a_formula_or_a_total_is_drawn_again_after_each_cell() -> None:
    fields = _fields(_node(_orders()))
    cells = {path: field for path, field in fields.items() if "/rows/" in path}

    assert cells and all(field.refresh for field in cells.values())
    # A label, a name, the title change nothing that is computed.
    assert not any(field.refresh for path, field in fields.items() if path not in cells)

    total_only = _node({"columns": ["Item", {"label": "Qty", "total": "sum"}],
                        "rows": [["Paper", 4]]})
    assert all(f.refresh for p, f in _fields(total_only).items() if "/rows/" in p)


def test_a_plain_sheet_follows_up_in_the_page_unless_only_python_knows_the_result() -> None:
    fields = _fields(_node(_every_type()))
    redrawn = {path for path, field in fields.items() if field.refresh}

    # The page writes these itself and the reader keeps the sort, filter and place.
    for path in ("0/name", "0/qty", "0/net", "0/share", "0/day", "1/day", "0/free",
                 "1/state/text", "0/src/text", "1/net", "3/name"):
        assert f"/sheets/0/rows/{path}" not in redrawn, path
    # A status word's tone, whether a text is an address, text in a number column.
    assert redrawn == {
        "/sheets/0/rows/0/state",
        "/sheets/0/rows/1/qty",
        "/sheets/0/rows/2/state",
        "/sheets/0/rows/2/src",
        "/sheets/0/rows/3/state",
        "/sheets/0/rows/3/src",
    }
    # Toggles are always drawn again by the bridge; the page script follows up the rest.
    page = render(_node(_every_type()))
    assert "node-field-saved" in page and 'setAttribute("data-refresh"' in page


def test_a_spec_that_is_not_stored_as_drawn_offers_no_cell_and_no_label() -> None:
    raw = {"columns": ["Item", "Qty"], "rows": [["Paper", 4], [], ["Toner", 2]]}
    fields = editable_fields(render(_node(raw, normalized=False)))

    # Its rows would not be where the page draws them: only the title is offered.
    assert [field.at for field in fields] == ["@title"]


def test_a_hostile_value_is_offered_as_itself_and_drawn_escaped() -> None:
    for payload in (SCRIPT, BREAKOUT):
        spec = {
            "note": payload,
            "sheets": [
                {"name": payload, "columns": [
                    {"key": "t", "label": payload},
                    {"key": "d", "label": "D", "type": "date"},
                    {"key": "l", "label": "L", "type": "link"},
                ], "rows": [[payload, payload,
                             {"text": payload, "href": "https://example.org/" + payload}]]},
                {"name": "Two", "columns": ["A"], "rows": []},
            ],
        }
        node = _node(spec, title=payload)
        page = render(node)
        fields = _fields(node)

        assert fields["/sheets/0/rows/0/d"].src == payload
        assert fields["/sheets/0/rows/0/l/text"].src == payload
        assert f'data-src="{escape(payload, quote=True)}"' in page
        drawn = _view(page)
        assert payload not in page and payload not in drawn
        # The page's own scripts are the only ones: the theme, the bridge, the grid.
        assert "<img" not in page and drawn.count("<script>") == 3


# ------------------------------------------------------------------- preview


def test_preview_is_the_top_left_corner_of_the_first_sheet() -> None:
    spec = normalize(_orders())
    spec["sheets"].append({"name": "Other", "columns": [{"key": "x", "label": "X"}], "rows": []})
    assert preview(spec) == {
        "columns": ["Item", "Qty", "Price"],
        "rows": [["Paper", "4", "5.50"], ["Toner", "2", "39.00"], ["Desk", "1", ""]],
        "numeric": [False, True, True],
        "count": 3,
    }


def test_preview_is_bounded_computes_formulas_and_writes_cells_as_text() -> None:
    spec = normalize(
        {
            "columns": [
                {"key": "share", "label": "S" * 80, "type": "percent", "formula": "a / b * 100"},
                {"key": "ok", "label": "OK", "type": "check"},
                {"key": "src", "label": "Source", "type": "link"},
                {"key": "a", "label": "A"},
                {"key": "b", "label": "B"},
            ],
            "rows": [
                {"ok": True, "src": "https://example.org/a/very/long/path/to/a/file", "a": 1,
                 "b": 8},
                {"ok": False, "src": {"text": "Doc", "href": "https://example.org"}, "a": 1,
                 "b": 0},
            ]
            + [{"a": i, "b": 2} for i in range(10)],
        }
    )
    card = preview(spec)

    assert set(card) == {"columns", "rows", "numeric", "count"}
    assert card["columns"] == ["S" * 24, "OK", "Source"]
    assert card["rows"] == [
        ["12.5%", "✓", "example.org/a/very/long/"],
        ["", "", "Doc"],
        ["0.0%", "", ""],
    ]
    assert card["numeric"] == [True, False, False] and card["count"] == 12
    assert all(len(cell) <= 24 for row in card["rows"] for cell in row)


def test_preview_of_nothing_is_empty_and_never_raises() -> None:
    nothing = {"columns": [], "rows": [], "numeric": [], "count": 0}
    assert preview({}) == nothing
    assert preview({"sheets": []}) == nothing
    assert preview({"sheets": ["x"]}) == nothing
    loose = {"sheets": [{"columns": [{"key": "a", "label": "A", "formula": "import os"}],
                         "rows": [{"a": 1}]}]}
    assert preview(loose)["columns"] == ["A"]


# --------------------------------------------------------- starter and guide


def test_the_starter_is_a_text_a_number_and_a_status_column() -> None:
    spec = starter("Budget", "en")
    assert normalize(spec) == spec
    sheet = spec["sheets"][0]
    assert [c["type"] for c in sheet["columns"]] == ["text", "number", "status"]
    assert len(sheet["rows"]) == 3 and len(spec["sheets"]) == 1
    assert "<tfoot>" in render(_node(spec, title="Budget"))


def test_the_guide_is_compact_and_its_example_is_a_valid_sheet() -> None:
    assert len(GUIDE) <= 2_500
    assert json.dumps(EXAMPLE, ensure_ascii=False) in GUIDE
    for word in ("formula", "total", "freeze", "status", "currency"):
        assert word in GUIDE

    spec = normalize(EXAMPLE)
    assert normalize(spec) == spec
    columns = spec["sheets"][0]["columns"]
    assert any("formula" in c for c in columns) and any("total" in c for c in columns)
    _columns, rows = sheets._read(spec["sheets"][0])
    assert [row["amount"] for row in rows] == [22.0, 78.0]
