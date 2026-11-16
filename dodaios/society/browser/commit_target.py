"""What a browser action is about to press, read from the page by the worker.

The host decides whether a step commits something for the person
(``commit_gate.py``) and what the approval card says. For that it needs the
control's own words: its label, what kind of control it is, and the dialog or
form around it. This module reads exactly that and nothing else, for a click
on an indexed element and for an Enter key in the focused field.

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
      context, field: squash(field + " " + role),
    };
  }
  const composer = tag === "textarea" || el.isContentEditable;
  if (!composer) return null;
  const typed = squash(el.value || el.innerText).slice(0, 600);
  if (!typed) return null;
  return {tag, type: "composer", role: "", href: "", label: "Enter", context: typed, field};
}"""


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
            break
        parent = getattr(parent, "parent_node", None)
    return {
        "tag": tag,
        "type": str(attrs.get("type") or "").lower(),
        "role": str(attrs.get("role") or getattr(ax, "role", "") or "").lower(),
        "href": str(attrs.get("href") or ""),
        "label": _squash(label, _LABEL_CHARS),
        "context": _squash(context, _CONTEXT_CHARS),
        "field": "",
    }


async def describe_target(proposal: dict, browser_session: Any, page: Any) -> dict[str, str] | None:
    """What ``proposal`` presses: the indexed control, or the focused field for Enter.

    ``page`` is an awaitable that yields the focused page; it is only awaited
    for a key press.
    """
    try:
        async with asyncio.timeout(_READ_TIMEOUT_S):
            for name, params in proposal.items():
                if not isinstance(params, dict):
                    continue
                if name in {"click", "click_element_by_index"} and params.get("index") is not None:
                    lookup = getattr(browser_session, "get_element_by_index", None)
                    if not callable(lookup):
                        return None
                    return describe_node(await lookup(int(params["index"])))
                if name == "send_keys" and "enter" in str(params.get("keys") or "").lower():
                    found = await (await page()).evaluate(_ACTIVE_SCRIPT)
                    return dict(found) if isinstance(found, dict) else None
    except Exception:  # noqa: BLE001 - reading a label never fails the action
        return None
    return None
