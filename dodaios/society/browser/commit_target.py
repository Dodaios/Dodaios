"""What a browser action is about to press, read from the page by the worker.

The host decides whether a step commits something for the person
(``commit_gate.py``) and what the approval card says. For that it needs the
control's own words: its label, what kind of control it is, and the dialog or
form around it. This module reads exactly that and nothing else, for a click
on an indexed element, a click by coordinates and an Enter key in the focused
field.

Runs inside the browser worker next to ``live_runner.py``: no imports from the
app, and no import of the browser library (its nodes are read by attribute).
Reading never fails an action: anything unreadable yields ``None`` and the
step runs as ordinary page work.
"""

from __future__ import annotations

import asyncio
from typing import Any

_LABEL_CHARS = 160
_CONTEXT_CHARS = 600
_ANCESTOR_DEPTH = 14
_READ_TIMEOUT_S = 3.0

#: The focused field and the control its Enter would press, as one JS object.
_ACTIVE_SCRIPT = """() => {
  const squash = (s) => (s || "").replace(/\\s+/g, " ").trim();
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el || el === document.body) return null;
  const tag = el.tagName.toLowerCase();
  const field = squash([
    el.getAttribute("type"), el.getAttribute("name"), el.id, el.getAttribute("placeholder"),
    el.getAttribute("aria-label"), el.getAttribute("role"),
  ].filter(Boolean).join(" "));
  const form = el.form || el.closest("form");
  const around = el.closest("dialog, [role=dialog], [role=alertdialog], form");
  const context = squash(around ? around.innerText : "").slice(0, 600);
  if (form) {
    const submit = form.querySelector(
      "button[type=submit], input[type=submit], button:not([type])"
    );
    const role = squash([form.getAttribute("role"), form.getAttribute("action")]
      .filter(Boolean).join(" "));
    return {
      tag: submit ? submit.tagName.toLowerCase() : "form",
      type: "submit", role: "", href: "",
      label: squash(submit ? (submit.innerText || submit.value
        || submit.getAttribute("aria-label")) : "").slice(0, 160),
      context, field: squash(field + " " + role), in_dialog: around && around !== form ? "1" : "",
    };
  }
  const composer = tag === "textarea" || el.isContentEditable;
  if (!composer) return null;
  const typed = squash(el.value || el.innerText).slice(0, 600);
  if (!typed) return null;
  return {
    tag, type: "composer", role: "", href: "", label: "Enter", context: typed, field,
    in_dialog: "",
  };
}"""


#: The control under a viewport point (a click by coordinates), as one JS object.
_POINT_SCRIPT = """([x, y]) => {
  const squash = (s) => (s || "").replace(/\\s+/g, " ").trim();
  let el = document.elementFromPoint(x, y);
  while (el && el.shadowRoot && el.shadowRoot.elementFromPoint(x, y)
      && el.shadowRoot.elementFromPoint(x, y) !== el) {
    el = el.shadowRoot.elementFromPoint(x, y);
  }
  if (!el) return null;
  const control = el.closest(
    "button, a, input, summary, label, [role=button], [role=menuitem], [role=link]"
  ) || el;
  const around = control.closest("dialog, [role=dialog], [role=alertdialog], form");
  return {
    tag: control.tagName.toLowerCase(),
    type: (control.getAttribute("type") || "").toLowerCase(),
    role: (control.getAttribute("role") || "").toLowerCase(),
    href: control.getAttribute("href") || "",
    label: squash(control.innerText || control.value || control.getAttribute("aria-label")
      || control.getAttribute("title") || control.getAttribute("alt")).slice(0, 160),
    context: squash(around ? around.innerText : "").slice(0, 600),
    field: "",
    in_dialog: around && around.tagName.toLowerCase() !== "form" ? "1" : "",
  };
}"""


def _viewport_point(params: dict, browser_session: Any) -> list[int]:
    """A click's model coordinates as viewport pixels (the library scales the same way)."""
    x, y = int(params["coordinate_x"]), int(params["coordinate_y"])
    shown = getattr(browser_session, "llm_screenshot_size", None)
    real = getattr(browser_session, "_original_viewport_size", None)
    if shown and real and shown[0] and shown[1]:
        return [int(x / shown[0] * real[0]), int(y / shown[1] * real[1])]
    return [x, y]


def _squash(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _children_text(node: Any) -> str:
    read = getattr(node, "get_all_children_text", None)
    if not callable(read):
        return ""
    try:
        return str(read() or "")
    except Exception:  # noqa: BLE001 - an unreadable subtree has no label
        return ""


def describe_node(node: Any) -> dict[str, str] | None:
    """The label, kind and surroundings of one DOM node of the browser library."""
    if node is None:
        return None
    attrs = dict(getattr(node, "attributes", None) or {})
    ax = getattr(node, "ax_node", None)
    tag = str(getattr(node, "tag_name", "") or getattr(node, "node_name", "") or "").lower()
    label = (
        _children_text(node)
        or str(getattr(ax, "name", "") or "")
        or str(attrs.get("aria-label") or attrs.get("value") or attrs.get("title") or "")
        or str(attrs.get("alt") or "")
    )
    context = ""
    in_dialog = False
    parent = getattr(node, "parent_node", None)
    for _ in range(_ANCESTOR_DEPTH):
        if parent is None:
            break
        parent_attrs = dict(getattr(parent, "attributes", None) or {})
        parent_tag = str(
            getattr(parent, "tag_name", "") or getattr(parent, "node_name", "") or ""
        ).lower()
        if parent_tag in {"dialog", "form"} or str(parent_attrs.get("role") or "").lower() in {
            "dialog",
            "alertdialog",
        }:
            context = _children_text(parent)
            in_dialog = parent_tag != "form"
            break
        parent = getattr(parent, "parent_node", None)
    return {
        "tag": tag,
        "type": str(attrs.get("type") or "").lower(),
        "role": str(attrs.get("role") or getattr(ax, "role", "") or "").lower(),
        "href": str(attrs.get("href") or ""),
        "label": _squash(label, _LABEL_CHARS),
        "context": _squash(context, _CONTEXT_CHARS),
        # What a field is for, so typing a card number can ask (``commit_gate.payment_step``).
        "field": _squash(
            " ".join(
                str(attrs.get(key) or "")
                for key in ("autocomplete", "name", "id", "placeholder", "aria-label")
            ),
            _LABEL_CHARS,
        ),
        "in_dialog": "1" if in_dialog else "",
    }


async def describe_target(proposal: dict, browser_session: Any, page: Any) -> dict[str, str] | None:
    """What ``proposal`` presses: the indexed control, the control under the
    clicked point, or the focused field for Enter.

    ``page`` is an awaitable that yields the focused page; it is only awaited
    for a click by coordinates and for a key press.
    """
    try:
        async with asyncio.timeout(_READ_TIMEOUT_S):
            for name, params in proposal.items():
                if not isinstance(params, dict):
                    continue
                if name in {"click", "click_element_by_index", "input", "input_text"} and (
                    params.get("index") is not None
                ):
                    lookup = getattr(browser_session, "get_element_by_index", None)
                    if not callable(lookup):
                        return None
                    return describe_node(await lookup(int(params["index"])))
                if name == "click" and params.get("coordinate_x") is not None:
                    # A model that clicks by coordinates names no element: the
                    # control under the point is read from the page instead.
                    point = _viewport_point(params, browser_session)
                    found = await (await page()).evaluate(_POINT_SCRIPT, point)
                    return dict(found) if isinstance(found, dict) else None
                if name == "send_keys" and "enter" in str(params.get("keys") or "").lower():
                    found = await (await page()).evaluate(_ACTIVE_SCRIPT)
                    return dict(found) if isinstance(found, dict) else None
    except Exception:  # noqa: BLE001 - reading a label never fails the action
        return None
    return None
