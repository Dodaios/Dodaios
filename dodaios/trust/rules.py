"""The person's standing rules: what the assistant may do without asking.

One rule covers one tool and one reach:

``tool``      every call of the tool (``Bash``).
``action``    one action of a connector (``gmail`` + ``send_message``).
``folder``    a file tool, for files inside one folder.
``command``   one exact shell command.

Rules are written by the approval card's "Always allow" (``AgentChatService``
calls :meth:`TrustRules.add`), listed and revoked on the Trust page, and read
by :meth:`TrustRules.allows` before a card is shown. A rule never covers an
action a hard limit guards (:mod:`dodaios.trust.hard_limits`): ``allows``
answers ``None`` for those, whatever is stored.

Persisted as JSON under the data dir so a rule survives a restart; the chat's
own per-session memory of "always" stays as it was and is simply shadowed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

from .hard_limits import action_of, bare_tool, hard_limit_for

log = logging.getLogger(__name__)

RULE_KINDS: Final[tuple[str, ...]] = ("tool", "action", "folder", "command")


class TrustRules:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._rules: list[dict[str, Any]] = []
        self._loaded = False

    # ------------------------------------------------------------ storage

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # no rule was ever saved: an empty store
            return
        except (OSError, ValueError) as exc:
            log.warning("trust rules: could not read %s: %s", self._path, exc)
            return
        items = raw.get("rules") if isinstance(raw, dict) else None
        if isinstance(items, list):
            self._rules = [r for r in items if isinstance(r, dict) and r.get("id")]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"rules": self._rules}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("trust rules: could not write %s: %s", self._path, exc)

    # ------------------------------------------------------------ API

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load()
            return [dict(r) for r in self._rules]

    def get(self, rule_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            return next((dict(r) for r in self._rules if r["id"] == rule_id), None)

    def add(
        self,
        *,
        tool: str,
        kind: str,
        target: str = "",
        label: str = "",
        app: str = "",
        source: str = "card",
    ) -> dict[str, Any]:
        """Add a rule (or return the identical one already stored)."""
        if kind not in RULE_KINDS:
            raise ValueError(f"kind must be one of {RULE_KINDS}")
        bare = bare_tool(tool)
        if not bare:
            raise ValueError("a rule needs a tool")
        if kind != "tool" and not target:
            raise ValueError(f"a {kind} rule needs a target")
        with self._lock:
            self._load()
            for rule in self._rules:
                if (
                    rule.get("tool", "").lower() == bare.lower()
                    and rule.get("kind") == kind
                    and _same_target(kind, str(rule.get("target") or ""), target)
                ):
                    return dict(rule)
            rule = {
                "id": uuid.uuid4().hex[:12],
                "tool": bare,
                "kind": kind,
                "target": target if kind != "tool" else "",
                "label": label or target or bare,
                "app": app,
                "source": source,
                "created_ms": int(time.time() * 1000),
            }
            self._rules.append(rule)
            self._save()
            return dict(rule)

    def revoke(self, rule_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            for index, rule in enumerate(self._rules):
                if rule["id"] == rule_id:
                    del self._rules[index]
                    self._save()
                    return dict(rule)
        return None

    def allows(
        self, tool: str, args: dict[str, Any] | None, *, cwd: str = ""
    ) -> dict[str, Any] | None:
        """The rule that lets this call run without a card, or ``None``.

        A hard limit wins over every rule: the call asks.
        """
        args = args if isinstance(args, dict) else {}
        if hard_limit_for(tool, args) is not None:
            return None
        bare = bare_tool(tool)
        with self._lock:
            self._load()
            rules = [dict(r) for r in self._rules if r.get("tool", "").lower() == bare.lower()]
        if not rules:
            return None
        from dodaios.agent_chat.approval_card import narrow_matches

        verb = action_of(args)
        for rule in rules:
            kind = rule.get("kind")
            if kind == "tool":
                return rule
            if kind == "action" and verb and verb == str(rule.get("target") or "").lower():
                return rule
            if kind in ("folder", "command"):
                try:
                    if narrow_matches(
                        {"tool": bare, "kind": kind, "value": str(rule.get("target") or "")},
                        tool,
                        args,
                        cwd,
                    ):
                        return rule
                except Exception:  # noqa: BLE001 — an unreadable rule never widens anything
                    log.warning("trust rules: could not match %s", rule.get("id"), exc_info=True)
        return None


def _same_target(kind: str, stored: str, wanted: str) -> bool:
    if kind == "tool":
        return True
    if kind == "folder":
        import os

        def norm(path: str) -> str:
            return os.path.normcase(os.path.normpath(path))

        return norm(stored) == norm(wanted)
    return stored.strip().lower() == wanted.strip().lower()


_DEFAULT: list[TrustRules] = []


def trust_rules() -> TrustRules:
    """The process-wide rule store under the data dir (built on first use)."""
    if not _DEFAULT:
        from dodaios.core.config import DATA_DIR

        _DEFAULT.append(TrustRules(Path(DATA_DIR) / "trust" / "rules.json"))
    return _DEFAULT[0]


def set_trust_rules(store: TrustRules | None) -> None:
    """Swap the process-wide store (tests, a custom data dir)."""
    _DEFAULT.clear()
    if store is not None:
        _DEFAULT.append(store)


__all__ = ["RULE_KINDS", "TrustRules", "set_trust_rules", "trust_rules"]
