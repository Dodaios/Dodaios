"""Approval cards, standing rules and their persistence."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.plan_review import PlanReview


class ApprovalsMixin:
    """Approval cards, standing rules and their persistence."""

    # ------------------------------------------------------------ approvals

    async def _ask(
        self,
        session_id: str,
        turn_id: str,
        call_id: str,
        name: str,
        args: dict[str, Any],
        summary: str,
    ) -> str:
        # A hard limit (money, credentials, deleting for good, a new recipient)
        # always asks: no rule of the person's, however it was saved, covers it.
        from dodaios.trust.hooks import before_execute

        if self.deferred_approvals.take_grant(session_id, name, args):
            # The person approved exactly this call on a card they had set aside
            # (approval_defer.py): their click, given earlier, answers it.
            return "allow"
        limited = before_execute(name, args).needs_person
        if not limited:
            # The same tool call asked again after a restart answers on the card
            # the person already sees (_hold_unanswered_approvals).
            if self._narrow_allows(session_id, name, args):
                # The person's own narrow rule from an earlier card covers this call.
                return "allow"
            if name in self._tool_always.get(session_id, ()):
                return "allow"
            if self._standing_rule_allows(session_id, name, args):
                return "allow"
        held = self._unanswered.pop((session_id, turn_id, call_id), "") if call_id else ""
        approval_id = held if held and held not in self._approvals else uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._approvals[approval_id] = fut
        self._approval_session[approval_id] = session_id
        self._approval_call[approval_id] = (name, args)
        await self._emit(
            session_id,
            _s.make_event(
                "approval_required",
                {
                    **self._approval_card(session_id, name, args, summary),
                    "turn_id": turn_id,
                    "approval_id": approval_id,
                    "call_id": call_id,
                    "name": name,
                    "input": args,
                    "summary": summary,
                },
            ),
        )
        try:
            decision = await fut
        except asyncio.CancelledError:
            # Nobody will answer this card any more (the ticket expired or was
            # decided elsewhere, or the turn stopped). Close it, so it cannot
            # take a click that would no longer reach anything.
            try:
                await self._emit(
                    session_id,
                    _s.make_event(
                        "approval_resolved",
                        {"turn_id": turn_id, "approval_id": approval_id, "decision": "cancel"},
                    ),
                )
            except Exception:  # noqa: BLE001 — the cancellation must still propagate
                _s.log.warning("agent chat: could not close approval card %s", approval_id)
            raise
        finally:
            self._approvals.pop(approval_id, None)
            self._approval_session.pop(approval_id, None)
            self._approval_call.pop(approval_id, None)
            edits = self._approval_edits.pop(approval_id, None)
            choice = self._approval_choice.pop(approval_id, None)
            feedback = self._approval_feedback.pop(approval_id, "")
            if feedback and call_id:
                self._deny_feedback[(session_id, call_id)] = feedback
        if decision == "defer":
            # The person moved on: the call is refused with the reason, the card
            # stays open, and its later answer continues the work.
            await self.deferred_approvals.set_aside(
                _s.Deferred(session_id, turn_id, approval_id, call_id, name, dict(args), summary)
            )
            self._deny_feedback[(session_id, call_id)] = _s.DEFER_NOTICE
            return "deny"
        changed: dict[str, dict[str, str]] = {}
        if edits and decision in ("allow", "allow_always"):
            from dodaios.agent_chat.approval_preview import EditRejected, apply_edits
            from dodaios.trust.hooks import before_execute as _gate

            try:
                new_args, changed = apply_edits(name, args, edits)
                gate = _gate(name, new_args)
            except EditRejected as exc:
                _s.log.info("agent chat: inline edit of %s rejected: %s", name, exc)
                decision, changed = "deny", {}
                self._deny_feedback[(session_id, call_id)] = f"The edit was rejected: {exc}."
            else:
                if gate.blocked:
                    decision, changed = "deny", {}
                    self._deny_feedback[(session_id, call_id)] = (
                        f"The edited version was blocked: {gate.block_reason()}."
                    )
                elif changed:
                    # The runner that asked sends these very arguments on: the
                    # edit is what runs (and the executor checks it again).
                    args.clear()
                    args.update(new_args)
        if decision == "allow_always":
            from dodaios.trust.hard_limits import NO_RULE_LIMITS, hard_limit_for

            if hard_limit_for(name, args) in NO_RULE_LIMITS:
                # Money, credentials, deleting for good: this call runs once
                # and nothing is remembered, whatever the answer asked for.
                decision = "allow"
        await self._emit(
            session_id,
            _s.make_event(
                "approval_resolved",
                {
                    "turn_id": turn_id,
                    "approval_id": approval_id,
                    "decision": decision,
                    **({"scope": choice[0]} if decision == "allow_always" and choice else {}),
                    **({"edited": changed} if changed else {}),
                    # The plan that is built, whole: the timeline shows it in
                    # place of the agent's own (``edited`` clips long texts).
                    **(
                        {"plan": str(args.get("plan") or "")}
                        if "plan" in changed and _s.plan_review.is_plan_tool(name)
                        else {}
                    ),
                },
            ),
        )
        if decision == "allow_always":
            session = self.store.get_session(session_id)
            if choice is not None and session is not None:
                scope, breadth, narrow = choice
                try:
                    saved = await self._rule_from_card(
                        session,
                        approval_id,
                        turn_id,
                        name,
                        args,
                        "always_allow",
                        scope,
                        breadth,
                        narrow,
                    )
                except Exception:  # noqa: BLE001 — falls back to the surface's own "always"
                    _s.log.warning(
                        "agent chat: rule from the card failed for %s", name, exc_info=True
                    )
                    saved = None
                if saved is not None:
                    if narrow:
                        # Only the narrow rule was asked for: the runtime that
                        # asked must not widen it to the whole tool.
                        return "allow"
                    if choice[0] == "agent":
                        from dodaios.agent_chat.approval_bridge import _bare

                        self._ruled_on_agent.setdefault(session_id, set()).add(_bare(name))
                    return decision
                if narrow:
                    # A narrow rule that could not be saved never widens to the
                    # whole tool or the whole chat: this call runs once.
                    return "allow"
            handled = False
            hook = _s.kit_for(session.surface).session_always_allow if session is not None else None
            if hook is not None:
                # A surface with its own memory for "always allow" (a society
                # agent's approval rules) keeps the session's stance untouched.
                try:
                    handled = bool(await hook(session, name, args))
                except Exception:  # noqa: BLE001 — falls back to the session-wide default below
                    _s.log.warning(
                        "agent chat: always-allow hook failed for %s", name, exc_info=True
                    )
            if handled:
                pass
            elif session is not None and session.surface in ("jarvis", "society"):
                # A society chat whose tool no agent rule governs (a runtime's
                # own Edit or Bash) stops asking for that one tool, never for
                # the whole chat.
                self._always_allowed.setdefault(session_id, set()).add(name)
            elif session is not None and _s.session_runner(session) not in (
                "claude-cli",
                "glm-cli",
            ):
                # "Always allow" stops asking for this tool, as in a terminal;
                # the thread's access mode stays what the person picked.
                self._tool_always.setdefault(session_id, set()).add(name)
            # Claude Code: the runner hands the CLI the rule it offered
            # (:meth:`cli_session_rules`); nothing else changes.
        return decision

    def cli_session_rules(self, session_id: str) -> list[dict[str, Any]]:
        """The Claude Code session rules "Always allow" collected in this session."""
        return self._cli_rules.setdefault(session_id, [])

    def take_deny_feedback(self, session_id: str, call_id: str) -> str:
        """What the person typed when declining the card of ``call_id``, once."""
        return self._deny_feedback.pop((session_id, call_id), "")

    def always_allowed(self, session_id: str) -> set[str]:
        """The tools waved through with "always allow" in this session (Jarvis surface)."""
        return self._always_allowed.setdefault(session_id, set())

    def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        decision: str,
        *,
        scope: str = "",
        breadth: str = "",
        narrow: str = "",
        feedback: str = "",
        edits: dict[str, Any] | None = None,
        review: PlanReview | None = None,
    ) -> bool:
        """Answer an open card. ``scope``/``breadth`` say where an "Always allow"
        lives (the card's rule editor), ``narrow`` how far a chat rule reaches;
        without them it does what it always did.

        ``edits`` maps an editable preview field to the person's new text (a
        mail's subject or body, an event's title or time). An edit that the
        action does not allow raises ``ValueError`` and the card stays open;
        an accepted one is what runs (``_ask`` amends the call's arguments).

        ``review`` is the person's review of a plan (``plan_review``): approved,
        the plan runs as they left it, their comments as its closing notes;
        declined, their comments and their version are the reason the agent
        reads. Only a plan card takes one."""
        if decision not in _s.DECISIONS:
            raise ValueError(f"decision must be one of {_s.DECISIONS}")
        if scope and scope not in _s.RULE_SCOPES:
            raise ValueError(f"scope must be one of {_s.RULE_SCOPES}")
        if breadth and breadth not in _s.RULE_BREADTHS:
            raise ValueError(f"breadth must be one of {_s.RULE_BREADTHS}")
        if narrow and narrow not in _s.RULE_NARROWS:
            raise ValueError(f"narrow must be one of {_s.RULE_NARROWS}")
        if narrow and scope != "chat":
            raise ValueError("a narrow rule lives in this chat")
        deferred = self.deferred_approvals.session_of(approval_id) == session_id
        feedback_limit = 2000
        if review is not None:
            item = self.deferred_approvals.get(approval_id) if deferred else None
            call = (item.name, item.args) if item else self._approval_call.get(approval_id)
            if call is None:
                return False
            if not _s.plan_review.is_plan_tool(call[0]):
                raise ValueError("only a plan takes a review")
            original = str(call[1].get("plan") or "")
            if decision == "deny":
                # The typed reason is the review's note on the whole plan.
                said = _s.replace(review, note=review.note or feedback.strip()[:2000])
                feedback = _s.plan_review.changes_wanted(original, said) or feedback
                feedback_limit = _s.plan_review.PLAN_CHARS + 20_000
            else:
                approved = _s.plan_review.approved_plan(original, review)
                if approved != original:
                    edits = {**(edits or {}), "plan": approved}
        if deferred:
            return self._answer_deferred(approval_id, decision, edits)
        if self._approval_session.get(approval_id) != session_id:
            return False
        fut = self._approvals.get(approval_id)
        if fut is None or fut.done():
            return False
        if edits and decision in ("allow", "allow_always"):
            from dodaios.agent_chat.approval_preview import EditRejected, apply_edits

            call = self._approval_call.get(approval_id)
            try:
                if call is not None:
                    apply_edits(call[0], call[1], edits)
            except EditRejected as exc:
                raise ValueError(str(exc)) from exc
            self._approval_edits[approval_id] = dict(edits)
        if decision == "allow_always" and scope:
            self._approval_choice[approval_id] = (scope, breadth or "action", narrow)
        if decision == "deny" and feedback.strip():
            self._approval_feedback[approval_id] = feedback.strip()[:feedback_limit]
        fut.set_result(decision)
        return True

    def _answer_deferred(
        self, approval_id: str, decision: str, edits: dict[str, Any] | None
    ) -> bool:
        """The person answers a card that was set aside while they wrote on."""
        from dodaios.agent_chat.approval_preview import EditRejected, apply_edits

        item = self.deferred_approvals.get(approval_id)
        new_args: dict[str, Any] = dict(item.args)
        changed: dict[str, dict[str, str]] = {}
        if edits and decision != "deny":
            try:
                new_args, changed = apply_edits(item.name, item.args, edits)
            except EditRejected as exc:
                raise ValueError(str(exc)) from exc
            from dodaios.trust.hooks import before_execute

            gate = before_execute(item.name, new_args)
            if gate.blocked:
                raise ValueError(f"The edited version was blocked: {gate.block_reason()}.")
        return self.deferred_approvals.answer(approval_id, decision, changed, new_args)

    def defer_open_approvals(self, session_id: str) -> int:
        """Set aside every card this chat's running turn waits on (the person moved on)."""
        count = 0
        for approval_id, sid in list(self._approval_session.items()):
            fut = self._approvals.get(approval_id)
            if sid == session_id and fut is not None and not fut.done():
                fut.set_result("defer")
                count += 1
        return count

    def _approval_card(
        self, session_id: str, name: str, args: dict[str, Any], summary: str
    ) -> dict[str, Any]:
        """The card's display fields (approval_card.py); empty when unavailable."""
        from dodaios.agent_chat.approval_card import describe_call, rule_offer

        try:
            session = self.store.get_session(session_id)
            surface = session.surface if session is not None else ""
            agent_rule = None
            if surface == "society":
                from dodaios.society.approvals import card_rule

                agent_rule = card_rule(name, args or {})
            rule = rule_offer(surface, name, args or {}, agent_rule)
            cwd = str(session.cwd or "") if session is not None else ""
            return describe_call(name, args, summary, cwd=cwd, rule=rule)
        except Exception:  # noqa: BLE001 — the card still asks with its name and summary
            _s.log.warning(
                "agent chat: approval card fields unavailable for %s", name, exc_info=True
            )
            return {}

    async def _rule_from_card(
        self,
        session: Any,
        approval_id: str,
        turn_id: str,
        name: str,
        args: dict[str, Any],
        kind: str,
        scope: str,
        breadth: str,
        narrow: str = "",
    ) -> dict[str, Any] | None:
        """Save the rule a card asked for and note it on the card; ``None`` if none fits.

        ``agent``: the society agent's own approval rules (persistent).
        ``chat``: this conversation stops asking for this tool until the app
        restarts (the Jarvis and society surfaces, whose tools ask through the
        approval bridge). Nothing else is ever widened from here.
        """
        from dodaios.agent_chat.approval_bridge import _bare
        from dodaios.agent_chat.approval_card import app_label
        from dodaios.trust.hard_limits import NO_RULE_LIMITS, hard_limit_for

        if kind == "always_allow" and hard_limit_for(name, args or {}) in NO_RULE_LIMITS:
            # No standing "always" for money, credentials or deleting for good.
            # (A new recipient asks anyway; the rule itself is fine to keep.)
            return None
        rule: dict[str, Any] | None = None
        if narrow:
            rule = self._narrow_rule_from_card(session, name, args or {}, kind, scope, narrow)
        elif scope == "agent" and session.surface == "society":
            from dodaios.society.approvals import save_card_rule

            rule = await save_card_rule(
                session.session_id, name, args or {}, kind=kind, breadth=breadth
            )
        elif (
            scope == "chat" and kind == "always_allow" and session.surface in ("society", "jarvis")
        ):
            bare = _bare(name)
            self._always_allowed.setdefault(session.session_id, set()).add(bare)
            rule = {"kind": kind, "pattern": bare, "app": app_label(bare), "verb": ""}
        if rule is None:
            return None
        if scope == "chat" and kind == "always_allow":
            # A chat rule outlives the chat: it is the person's standing rule,
            # listed and revocable on the Trust page (dodaios/trust/rules.py).
            standing = self._persist_standing_rule(session, name, args or {}, rule)
            if standing is not None:
                rule["rule_id"] = standing["id"]
        await self._emit(
            session.session_id,
            _s.make_event(
                "notice",
                {
                    "kind": "approval_rule",
                    "turn_id": turn_id,
                    "approval_id": approval_id,
                    "rule_kind": rule["kind"],
                    "scope": scope,
                    "pattern": rule["pattern"],
                    "app": rule.get("app", ""),
                    "verb": rule.get("verb", ""),
                    "still_asks": bool(rule.get("still_asks")),
                    **({"rule_id": rule["rule_id"]} if rule.get("rule_id") else {}),
                    **(
                        {"narrow": rule["narrow"], "target": rule.get("target", "")}
                        if rule.get("narrow")
                        else {}
                    ),
                },
            ),
        )
        return rule

    # ------------------------------------------------------------ standing rules

    def _persist_standing_rule(
        self, session: Any, name: str, args: dict[str, Any], rule: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Write a chat rule into the person's standing rules; ``None`` if that failed."""
        from dodaios.agent_chat.approval_bridge import _bare
        from dodaios.agent_chat.approval_card import narrow_tool
        from dodaios.trust.rules import trust_rules

        try:
            narrow = str(rule.get("narrow") or "")
            if narrow:
                entry = next(
                    (
                        r
                        for r in self._narrow_rules.get(session.session_id, [])
                        if r.get("kind") == narrow
                        and r.get("tool", "").lower() == narrow_tool(name).lower()
                    ),
                    None,
                )
                target = str((entry or {}).get("value") or "")
                if not target:
                    return None
                return trust_rules().add(
                    tool=narrow_tool(name),
                    kind=narrow,
                    target=target,
                    label=str(rule.get("target") or target),
                    app=str(rule.get("app") or ""),
                )
            return trust_rules().add(
                tool=_bare(name),
                kind="tool",
                label=str(rule.get("app") or _bare(name)),
                app=str(rule.get("app") or ""),
            )
        except Exception:  # noqa: BLE001 — the chat still remembers for this run
            _s.log.warning(
                "agent chat: could not persist a standing rule for %s", name, exc_info=True
            )
            return None

    def _standing_rule_allows(self, session_id: str, name: str, args: dict[str, Any]) -> bool:
        """Whether one of the person's standing rules (Trust page) covers this call."""
        from dodaios.trust.rules import trust_rules

        session = self.store.get_session(session_id)
        cwd = str(session.cwd or "") if session is not None else ""
        try:
            return trust_rules().allows(name, args or {}, cwd=cwd) is not None
        except Exception:  # noqa: BLE001 — no match: the card asks as usual
            _s.log.warning("agent chat: standing rule check failed for %s", name, exc_info=True)
            return False

    def forget_standing_rule(self, rule: dict[str, Any]) -> None:
        """A rule revoked on the Trust page stops covering calls in every open chat."""
        tool = str(rule.get("tool") or "").lower()
        kind = str(rule.get("kind") or "")
        target = str(rule.get("target") or "")
        if not tool:
            return
        if kind == "tool":
            for bag in (self._always_allowed, self._tool_always):
                for names in bag.values():
                    for name in [n for n in names if n.lower() == tool]:
                        names.discard(name)
            if self._bridge is not None:
                for grant in list(self._bridge._grants.values()):
                    for name in [n for n in grant.always_allowed if n.lower() == tool]:
                        grant.always_allowed.discard(name)
        elif kind in ("folder", "command"):
            for rules in self._narrow_rules.values():
                rules[:] = [
                    r
                    for r in rules
                    if not (
                        r.get("kind") == kind
                        and r.get("tool", "").lower() == tool
                        and r.get("value", "") == target
                    )
                ]

    # ------------------------------------------------------------ undo

    def _on_undo_recorded(self, entry: dict[str, Any]) -> None:
        """The undo ledger kept an inverse: tell the chat it came from (a quiet notice)."""
        session_id = str(entry.get("session_id") or "")
        if not session_id or self.store.get_session(session_id) is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # recorded off the loop (a sync test): no chat to tell
            return
        task = loop.create_task(
            self._emit(
                session_id,
                _s.make_event(
                    "notice",
                    {
                        "kind": "undo_available",
                        "undo_id": entry.get("id"),
                        "tool": entry.get("tool"),
                        "text": entry.get("label") or "",
                        "expires_ms": entry.get("expires_ms"),
                        **({"turn_id": t} if (t := self._running_turn_id(session_id)) else {}),
                    },
                ),
            ),
            name=f"agent-chat-undo-notice-{session_id[:8]}",
        )
        self._question_tasks.add(task)
        task.add_done_callback(self._question_tasks.discard)

    def _narrow_rule_from_card(
        self,
        session: Any,
        name: str,
        args: dict[str, Any],
        kind: str,
        scope: str,
        narrow: str,
    ) -> dict[str, Any] | None:
        """Remember "only this folder" / "only this command" for this chat."""
        from dodaios.agent_chat.approval_card import (
            app_label,
            narrow_options,
            narrow_tool,
            source_of,
        )

        if kind != "always_allow" or scope != "chat":
            return None
        cwd = str(session.cwd or "")
        offered = narrow_options(source_of(name, args)["kind"], args, cwd)
        match = next((o for o in offered if o["kind"] == narrow), None)
        if match is None:
            return None
        # The same name narrow_matches compares against later.
        bare = narrow_tool(name)
        rules = self._narrow_rules.setdefault(session.session_id, [])
        entry = {"tool": bare, "kind": narrow, "value": match["value"]}
        if entry not in rules:
            rules.append(entry)
        return {
            "kind": kind,
            "pattern": f"{narrow}:{match['value']}",
            "app": app_label(bare),
            "verb": "",
            "narrow": narrow,
            "target": match["label"],
        }

    def _narrow_allows(self, session_id: str, name: str, args: dict[str, Any]) -> bool:
        """Whether a narrow chat rule saved from an earlier card covers this call."""
        rules = self._narrow_rules.get(session_id)
        if not rules:
            return False
        from dodaios.agent_chat.approval_card import narrow_matches

        session = self.store.get_session(session_id)
        cwd = str(session.cwd or "") if session is not None else ""
        try:
            return any(narrow_matches(rule, name, args or {}, cwd) for rule in rules)
        except Exception:  # noqa: BLE001 — no match: the card asks as usual
            _s.log.warning("agent chat: narrow rule check failed for %s", name, exc_info=True)
            return False

    async def save_approval_rule(
        self,
        session_id: str,
        approval_id: str,
        *,
        kind: str,
        scope: str,
        breadth: str = "action",
        narrow: str = "",
    ) -> dict[str, Any]:
        """A rule from a card already answered (or expired): "Allow every
        time", "Check with me every time". Raises KeyError for an unknown
        card and LookupError when no rule fits that card in that scope."""
        if scope not in _s.RULE_SCOPES:
            raise ValueError(f"scope must be one of {_s.RULE_SCOPES}")
        if narrow and narrow not in _s.RULE_NARROWS:
            raise ValueError(f"narrow must be one of {_s.RULE_NARROWS}")
        session = self.store.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        asked: dict[str, Any] | None = None
        for event in await asyncio.to_thread(self.store.list_events, session_id):
            payload = event.get("payload") or {}
            if (
                event.get("kind") == "approval_required"
                and payload.get("approval_id") == approval_id
            ):
                asked = payload
        if asked is None:
            raise KeyError(approval_id)
        args = asked.get("input") if isinstance(asked.get("input"), dict) else {}
        rule = await self._rule_from_card(
            session,
            approval_id,
            str(asked.get("turn_id") or ""),
            str(asked.get("name") or ""),
            args,
            kind,
            scope,
            breadth,
            narrow,
        )
        if rule is None:
            raise LookupError("no rule fits this card")
        return rule

    async def close_stale_approval(self, session_id: str, approval_id: str) -> bool:
        """Close a card the transcript still shows open but nothing waits on.

        Its asker is gone — an app restart took the waiting call with it, or
        the CLI asked again under another card. Answering it can change
        nothing, so the card is closed for good instead of offering buttons
        that fail on every click and come back on every reload. Returns
        whether such a card was found.
        """
        if approval_id in self._approvals:
            return False
        turn_id = ""
        for event in await asyncio.to_thread(self.store.list_events, session_id):
            payload = event.get("payload") or {}
            if str(payload.get("approval_id") or "") != approval_id:
                continue
            if event.get("kind") == "approval_resolved":
                return False
            if event.get("kind") == "approval_required":
                turn_id = str(payload.get("turn_id") or "")
        if not turn_id:
            return False
        for key in [k for k, v in self._unanswered.items() if v == approval_id]:
            self._unanswered.pop(key, None)
        await self._emit(
            session_id,
            _s.make_event(
                "approval_resolved",
                {"turn_id": turn_id, "approval_id": approval_id, "decision": "expired"},
            ),
        )
        return True
