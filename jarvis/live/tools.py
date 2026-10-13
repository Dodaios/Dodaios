"""Model-selected tools with application-owned authorization and receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from jarvis.brain.cu_gate import CU_VEHICLE_TOOL_NAMES
from jarvis.control.cancel import CancelToken
from jarvis.core.protocols import SupervisorToolGateway, SupervisorToolRequest
from jarvis.live.state import LiveLedger
from jarvis.live.tasks import BackgroundTask, TaskBoard
from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL
from jarvis.speech.hangup import (
    HangupConfirmation,
    confirms_hangup,
    hangup_confirmation_question,
    user_asked_to_hang_up,
)

log = logging.getLogger(__name__)

# A session.started event includes its declarations. Keep room for prompts and
# history inside the 64 KiB message limit of smaller WebRTC clients.
_CATALOG_BYTE_BUDGET = 24_000
_BUILTIN_TOOLS = frozenset(
    {"discover_tools", "call_tool", "confirm_action", "end_call", "task_status"}
)
# An approval is a short answer made only of go-ahead words: "Ja, send ihn"
# approves (refused live 2026-10-01 by an exact-phrase list), while "yes,
# change the target" or "ja, aber warte" carry something else and do not.
_GO_AHEAD_WORDS = frozenset(
    {
        # English
        "yes", "yeah", "yep", "sure", "ok", "okay", "please", "confirm", "confirmed",
        "do", "it", "go", "ahead", "send", "run", "start", "that", "now",
        # German  # i18n-allow: spoken confirmation vocabulary
        "ja", "jo", "jep", "klar", "gerne", "genau", "bitte", "bestätigen",  # i18n-allow
        "bestätigt", "mach", "machs", "das", "es", "ihn", "sie",  # i18n-allow
        "schick", "schicke", "schicks",  # i18n-allow
        "sende", "senden", "los", "ab", "raus", "jetzt", "starte", "starten",  # i18n-allow
        # Spanish
        "sí", "si", "claro", "vale", "dale", "confirmo", "hazlo", "envía", "envialo",
        "envíalo", "adelante",
        # European Portuguese  # i18n-allow: spoken confirmation vocabulary
        "sim", "avança", "avanca", "força", "forca", "pode", "podes", "faz",
        "isso", "manda", "envia", "certo", "confirmado",
    }
)  # fmt: skip
_APPROVAL_LOCALES = ("de", "en", "es", "pt")
_RECENT_SEGMENTS = 4
_REQUEST_TEXT_CHARS = 1200
# Declared before every other tool so the size budget never drops them.
_PRIORITY_TOOLS = frozenset({"workspace-orchestrate", "find-app-action", "run-app-action"})
# Declared under its canonical name in every mode (see ``declarations``).
_DIRECT_TOOLS = frozenset({"computer", "take_appshot"})
# One screen, one mouse: these never run side by side, and a result that
# arrives after the user asked for something else describes a screen that has
# moved on. ``computer_use`` is the delegated vehicle for the same screen.
_SCREEN_TOOLS = _DIRECT_TOOLS | CU_VEHICLE_TOOL_NAMES
# The hang-up question is asked once: its state changes across an await.
# ``confirm_action`` takes its pending approval in one step and then runs the
# approved effect, which must not hold anything else up.
_CONTROL_TOOLS = frozenset({"end_call"})
# After the user moves on, an action that is about to finish still answers its
# own call; only one that keeps running becomes a background task.
MOVE_ON_GRACE_S = 0.6
_APPROVAL_NEXT_STEP = (
    "Ask the user to approve this action. After an explicit yes, call confirm_action "
    "directly (not through call_tool) with this approval_id. A yes is never a hang-up."
)


def _wire_size(value: Any) -> int:
    return len(json.dumps(value).encode("utf-8"))


def take_images(result: dict) -> list[dict]:
    """Separate actual image inputs from text function outputs and stored receipts."""
    images = []
    output = result.get("output")
    if isinstance(output, dict) and "_image" in output:
        output = dict(output)
        images.append(output.pop("_image"))
        result["output"] = output
    artifacts = result.get("artifacts", [])
    images.extend(a for a in artifacts if isinstance(a, dict) and a.get("type") == "image")
    result["artifacts"] = [
        a for a in artifacts if not isinstance(a, dict) or a.get("type") != "image"
    ]
    return images


def function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


class LiveTools:
    """Single execution owner, including when both RTC and sideband see events.

    Independent actions run side by side; only the screen and the session's
    own controls are serialized. An action that outlives its turn becomes a
    background task on ``tasks`` (see ``execute_releasable``).
    """

    def __init__(
        self,
        gateway: SupervisorToolGateway,
        ledger: LiveLedger,
        session_id: str,
        *,
        language: str,
        backend_model: str,
        model_selection: Any = None,
    ) -> None:
        self.gateway = gateway
        self.ledger = ledger
        self.session_id = session_id
        self.language = language
        self.backend_model = backend_model
        # Recent user caption segments, newest last (see ``user_text``).
        self._recent_user: list[str] = []
        self._hangup_confirmation = HangupConfirmation()
        self.ask_hangup: Any = None
        self.model_selection = model_selection
        self.user_text = ""
        self._revision = 0
        self._revision_waiters: list[asyncio.Future] = []
        self.cancel_token = CancelToken()
        self._screen_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        # One execution per call ID: RTC and the sideband can both deliver it.
        self._inflight: dict[str, tuple[str, str, asyncio.Future]] = {}
        # Calls that left their turn while still running (see ``_execute``).
        self._released: set[str] = set()
        self.tasks = TaskBoard()
        # The session's hooks for a task leaving its turn and for its receipt.
        self.on_task_released: Any = None
        self.on_task_finished: Any = None
        # The session's connection generation, stamped on every task.
        self.wire_epoch: Any = lambda: 0
        self._pending: dict[str, tuple[UUID, str, dict, int]] = {}
        self._names: dict[str, str] = {}
        self._defer_catalog = False
        self.end_requested = False
        self.accepting = True

    @property
    def revision(self) -> int:
        """Counts the user's requests: a changed value means they moved on."""
        return self._revision

    @revision.setter
    def revision(self, value: int) -> None:
        if value == self._revision:
            return
        self._revision = value
        waiters, self._revision_waiters = self._revision_waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    def catalog(self):
        read = getattr(self.gateway, "voice_catalog", self.gateway.catalog)
        return read()

    def accept_new_input(self) -> None:
        """New requests get a fresh token; running work keeps its cancelled token."""
        if self.cancel_token.is_cancelled():
            self.cancel_token = CancelToken()
        self.accepting = True

    async def cancel_work(self) -> None:
        self.cancel_token.cancel("user_cancelled")
        self.accepting = False
        self.revision += 1
        for task in self.tasks.cancel_all():
            log.info("Live background %s (%s) cancelled by the user", task.task_id, task.tool)
        await self._cancel_confirmations("user_cancelled")

    def declarations(self, *, defer_catalog: bool = False) -> list[dict]:
        self._defer_catalog = defer_catalog
        definitions = [
            function(
                "end_call",
                "Request voice hang-up. Dodaios asks for confirmation first; call again only "
                "after a separate explicit yes to that question. Never end a call for task "
                "completion or an action approval. Running agents keep their tasks.",
                {},
                [],
            ),
            function(
                "discover_tools",
                "Find Dodaios tools and their complete input schemas. Empty query browses all "
                "tools. Pass next_offset as offset to read the next page.",
                {"query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
                ["query"],
            ),
            function(
                "call_tool",
                "Execute a discovered Dodaios tool using its canonical name and JSON arguments.",
                {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
                ["name", "arguments_json"],
            ),
            function(
                "confirm_action",
                "Resume the exact pending action the user approved. Never infer approval.",
                {"approval_id": {"type": "string"}},
                ["approval_id"],
            ),
            function(
                "task_status",
                "List this call's background tasks: actions that kept running while the "
                "user moved on, each with its request, state and result. Use it when the "
                "user asks how far something is or what came out of it. Pass cancel with a "
                "task_id only when the user asks to stop that task.",
                {"cancel": {"type": "string"}},
                [],
            ),
        ]
        # The screen is operated in many short rounds (ADR-0039): declare the
        # computer tool under its own name instead of behind discover/call_tool.
        # Keep capture available even with a deferred catalog. Otherwise a live
        # model may reuse an old image or choose computer instead of the appshot
        # path that owns privacy filtering, the shutter effect and the receipt.
        for descriptor in self.catalog():
            if descriptor.name not in _DIRECT_TOOLS:
                continue
            definitions.append(
                {
                    "type": "function",
                    "name": descriptor.name,
                    "description": descriptor.description,
                    "parameters": descriptor.input_schema,
                }
            )
        if defer_catalog:
            definitions[1]["description"] = (
                "Find tools by intent using a few English keywords, or an exact canonical name. "
                "Returns relevant complete input schemas. Reuse schemas already read; do not "
                "inventory unrelated tools. Empty query browses all tools. Pass next_offset as "
                "offset with the same query to read another page only if needed."
            )
            # A names-only index lets the same model choose an exact capability
            # without asking lexical search to infer the user's intent.
            definitions[1]["description"] += " Available tool names: " + ", ".join(
                sorted(descriptor.name for descriptor in self.catalog())
            )
            definitions[1]["parameters"]["properties"]["offset"] = {"type": "integer", "minimum": 0}
            return definitions
        # Count alone is insufficient: an imported tool may carry a large schema.
        used_bytes = _wire_size(definitions)
        # The tools that steer the app itself go first: sorted by name alone,
        # workspace-orchestrate fell past the budget and voice could not open
        # or brief a coding agent (live 2026-10-01).
        ordered = sorted(self.catalog(), key=lambda d: (d.name not in _PRIORITY_TOOLS, d.name))
        for descriptor in ordered:
            if descriptor.name in _DIRECT_TOOLS:
                continue
            alias = "jarvis_" + hashlib.sha256(descriptor.name.encode()).hexdigest()[:20]
            definition = {
                "type": "function",
                "name": alias,
                "description": f"{descriptor.name}: {descriptor.description}",
                "parameters": descriptor.input_schema,
            }
            size = _wire_size(definition) + 2
            if len(definitions) >= 52 or used_bytes + size > _CATALOG_BYTE_BUDGET:
                continue
            used_bytes += size
            self._names[alias] = descriptor.name
            definitions.append(definition)
        return definitions

    async def execute(
        self, call_id: str, name: str, args: dict, revision: int,
        *, replay_result: dict | None = None,
    ) -> dict:
        identity = json.dumps(args, sort_keys=True, default=str)
        running = self._inflight.get(call_id)
        if running is not None and running[:2] == (name, identity):
            # The same call from the second transport waits for the first's
            # receipt. Shielded: giving up on the copy never stops the action.
            return await asyncio.shield(running[2])
        work = asyncio.ensure_future(
            self._execute_claimed(call_id, name, args, revision, replay_result)
        )
        if running is None:
            self._inflight[call_id] = (name, identity, work)
            work.add_done_callback(lambda _done: self._inflight.pop(call_id, None))
        return await work

    async def execute_releasable(
        self, call_id: str, name: str, args: dict, revision: int,
        *, deadline_s: float | None = None, replay_result: dict | None = None,
    ) -> dict:
        """Run a call, but stop waiting once it should not hold the conversation.

        An action still running when the user moves on to another request, and
        any call still running after ``deadline_s`` (a wire whose model is
        blocked on the result), becomes a background task: the caller gets a
        pending receipt now, the call keeps running, and the session reports
        its real receipt at a pause. Nothing is cancelled or repeated here.
        """
        token = self.cancel_token
        # Read now: by the time the call is released, the user's next words
        # are the latest segment, and they are not what this call answers.
        request = self.request_text
        # Resolved now: an approval is taken off the list once its effect runs.
        call = self._effect_of(name, args)
        work = asyncio.ensure_future(
            self.execute(call_id, name, args, revision, replay_result=replay_result)
        )
        try:
            released = await self._outlives_its_turn(work, name, args, revision, deadline_s)
        except asyncio.CancelledError:
            work.cancel()  # cancelling the call still cancels its tool
            raise
        if not released:
            return work.result()
        self._released.add(call_id)
        work.add_done_callback(lambda _done: self._released.discard(call_id))
        task = self.tasks.add(
            tool=call[0],
            arguments=call[1],
            summary=self._task_summary(*call),
            request_text=request,
            revision=revision,
            epoch=int(self.wire_epoch()),
            work=work,
            cancel_token=token,
            obsolete_on_new_request=not self._is_background_action(name, args),
        )
        work.add_done_callback(lambda done: self._task_settled(task, done))
        log.info(
            "Live tool %s keeps running as background %s (%s)",
            task.tool, task.task_id,
            "the user moved on" if revision != self.revision else "past its deadline",
        )
        if callable(self.on_task_released):
            self.on_task_released(task)
        return {
            "success": False,
            "pending": True,
            "status": "running_in_background",
            "task_id": task.task_id,
            "error": (
                f"This call is still running and continues in the background as "
                f"{task.task_id}. Its result is handed to you when it finishes. Tell the "
                "user in one short sentence that it is running, never that it is done; do "
                "not call it again, and carry on with the user's latest request. If that "
                "request needs this result, say it follows once the task has finished: you "
                "carry it out when the result arrives."
            ),
            "background_tasks": [item.describe() for item in self.tasks.running()],
        }

    async def _outlives_its_turn(
        self, work: asyncio.Future, name: str, args: dict, revision: int,
        deadline_s: float | None,
    ) -> bool:
        """Wait for ``work``; True once it has to continue without its caller."""
        loop = asyncio.get_running_loop()
        deadline = None if deadline_s is None else loop.time() + deadline_s
        action = self._is_background_action(name, args)
        while not work.done():
            if action and revision != self.revision:
                await asyncio.wait({work}, timeout=MOVE_ON_GRACE_S)
                return not work.done()
            timeout = None if deadline is None else deadline - loop.time()
            if timeout is not None and timeout <= 0:
                return True
            waiting: set[asyncio.Future] = {work}
            moved: asyncio.Future | None = None
            if action:
                moved = loop.create_future()
                self._revision_waiters.append(moved)
                waiting.add(moved)
            try:
                await asyncio.wait(waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if moved is not None and not moved.done():
                    moved.cancel()
                    if moved in self._revision_waiters:
                        self._revision_waiters.remove(moved)
        return False

    def _effect_of(self, name: str, args: dict) -> tuple[str, dict]:
        """The tool and arguments a call acts with; an approval names its action."""
        call = self._replay_call(name, args) or (name, args)
        if call[0] == "confirm_action":
            pending = self._pending.get(str(call[1].get("approval_id", "")))
            if pending is None and len(self._pending) == 1:
                pending = next(iter(self._pending.values()))
            if pending is not None:
                return pending[1], dict(pending[2])
        return call

    def _is_background_action(self, name: str, args: dict) -> bool:
        """An effect in the user's world whose outcome is owed whatever came next."""
        call = self._replay_call(name, args)
        if call is None or call[0] in _SCREEN_TOOLS:
            return False
        if call[0] == "confirm_action":
            return True  # the approved effect runs inside this call
        if call[0] in _BUILTIN_TOOLS:
            return False
        return not self._reads_only(*call)

    def _task_summary(self, tool: str, args: dict) -> str:
        descriptor = next((d for d in self.catalog() if d.name == tool), None)
        describe = getattr(descriptor, "describe_args", None)
        if callable(describe):
            try:
                detail = describe(args)
            except Exception:
                log.warning("Live task summary failed for %s", tool, exc_info=True)
            else:
                parts = [str(detail.get(key) or "") for key in ("agent", "workspace", "task")]
                text = " · ".join(part for part in parts if part)
                if text:
                    return f"{tool}: {text}"
        return tool

    def _task_status(self, args: dict) -> dict:
        wanted = str(args.get("cancel") or "").strip()
        if not wanted:
            return {"success": True, "tasks": self.tasks.snapshot()}
        task = self.tasks.get(wanted)
        if task is None or not self.tasks.cancel(task):
            return {
                "success": False,
                "executed": False,
                "error": "No running background task has that task_id.",
                "tasks": self.tasks.snapshot(),
            }
        log.info("Live background %s (%s) cancelled on request", task.task_id, task.tool)
        return {
            "success": True,
            "cancelled": task.task_id,
            "note": "Stopped. An effect that already happened is not undone.",
            "tasks": self.tasks.snapshot(),
        }

    def _task_settled(self, task: BackgroundTask, work: asyncio.Future) -> None:
        if not work.cancelled() and work.exception() is not None:
            log.warning(
                "Live background %s (%s) raised", task.task_id, task.tool,
                exc_info=work.exception(),
            )
        self.tasks.settle(task, work)
        if task.result is not None:
            # The action ran for its own request; that the user said more
            # meanwhile is why it is a background task, not a defect of it.
            task.result = {
                key: value for key, value in task.result.items()
                if key not in {"superseded", "task_revision", "current_revision"}
            }
        log.info(
            "Live background %s (%s) ended %s after %.0f s",
            task.task_id, task.tool, task.status, task.finished_at - task.started_at,
        )
        if callable(self.on_task_finished):
            self.on_task_finished(task)

    def _lane(self, name: str, args: dict) -> asyncio.Lock | None:
        """The lock a call runs under; ``None`` for independent work."""
        call = self._replay_call(name, args)
        canonical = call[0] if call is not None else name
        if canonical in _SCREEN_TOOLS:
            return self._screen_lock
        if canonical in _CONTROL_TOOLS:
            return self._control_lock
        return None

    async def _execute_claimed(
        self, call_id: str, name: str, args: dict, revision: int, replay_result: dict | None,
    ) -> dict:
        lane = self._lane(name, args)
        if lane is None:
            return await self._execute_recorded(call_id, name, args, revision, replay_result)
        async with lane:
            return await self._execute_recorded(call_id, name, args, revision, replay_result)

    async def _execute_recorded(
        self, call_id: str, name: str, args: dict, revision: int, replay_result: dict | None,
    ) -> dict:
        if (self._hangup_confirmation.pending_turn is not None
                and confirms_hangup(self.user_text) and name != "end_call"):
            return {
                "success": False, "executed": False,
                "error": "This yes answers the hang-up question, not an action approval.",
            }
        if not self.accepting:
            return {"success": False, "status": "voice_closed_before_execution"}
        receipt = await asyncio.to_thread(
            self.ledger.claim,
            self.session_id,
            call_id,
            name,
            args,
            revision,
        )
        if receipt is not None:
            return receipt
        try:
            if replay_result is not None and self.steering_replay_key(name, args) is None:
                result = {
                    "success": False, "executed": False,
                    "error": "Controls, approvals and reads require a fresh evaluation.",
                }
            elif replay_result is not None and revision == self.revision:
                # The session retained this result from an earlier execution.
                # Record the new model call ID without performing another effect.
                result = {**replay_result, "reused_receipt": True}
            else:
                result = await self._execute(name, args, revision, call_id=call_id)
        except asyncio.CancelledError:
            # Leave the claim uncertain: a cancelled request may already have acted.
            raise
        except Exception:
            log.exception("Live tool execution failed for %s", name)
            result = {
                "success": False,
                "error": "Tool execution failed; inspect its state before retrying.",
            }
        if revision != self.revision:
            result = {
                **result,
                "superseded": True,
                "task_revision": revision,
                "current_revision": self.revision,
            }
        receipt = dict(result)
        if isinstance(receipt.get("output"), dict):
            receipt["output"] = {k: v for k, v in receipt["output"].items() if k != "_image"}
        take_images(receipt)
        await asyncio.to_thread(self.ledger.finish, self.session_id, call_id, receipt)
        return result

    async def _execute(
        self, name: str, args: dict, revision: int, *, call_id: str = "",
    ) -> dict:
        operation_token = self.cancel_token
        if operation_token.is_cancelled():
            return {"success": False, "status": "cancelled"}
        if revision != self.revision and not self._reads_only(name, args):
            # Only an action can be overtaken by what the user said meanwhile;
            # a search or a read answers the same either way (11 reads were
            # discarded live and re-bought as paid rounds).
            return {
                "success": False,
                "executed": False,
                "status": "superseded",
                "error": "The request changed before execution. Re-evaluate the latest user input.",
            }
        if ":" in name:
            prefix, suffix = name.split(":", 1)
            if prefix.isidentifier() and (suffix in self._names or suffix in _BUILTIN_TOOLS):
                name = suffix
        if name == "call_tool" and args.get("name") in _BUILTIN_TOOLS - {"call_tool"}:
            # Models wrap the session built-ins too. They are not catalog tools,
            # so the catalog lookup below answered "no longer available".
            try:
                inner = json.loads(args.get("arguments_json") or "{}")
            except ValueError:  # bad JSON is answered by the object check just below
                inner = None
            if not isinstance(inner, dict):
                return {"success": False, "error": "Tool arguments must be an object."}
            name, args = str(args["name"]), inner
        if name == "end_call":
            decision = self._hangup_confirmation.observe(self.user_text, revision)
            if decision in {"request", "waiting"}:
                question = hangup_confirmation_question(self.language)
                if decision == "request" and callable(self.ask_hangup):
                    await self.ask_hangup(question)
                    self._hangup_confirmation.arm(revision)
                return {
                    "success": False, "executed": False,
                    "confirmation_required": True,
                    "question": question,
                    "next_step": "Dodaios asks this question. Wait for a separate explicit yes "
                    "and then call end_call again. Never confirm another action with this yes.",
                }
            if decision != "confirmed":
                # Live 2026-10-01: after "Ja" to a pending approval the model
                # called end_call instead of confirm_action and the call dropped.
                refusal: dict = {
                    "success": False,
                    "executed": False,
                    "error": "The user did not ask to hang up. Stay on the call.",
                }
                if self._pending:
                    refusal["approval_ids"] = list(self._pending)
                    refusal["next_step"] = (
                        "If the user approved, call confirm_action with the approval_id."
                    )
                log.info("Live end_call refused: the user's turn holds no hang-up request")
                return refusal
            self.end_requested = True
            return {"success": True, "status": "closing_voice"}
        if name == "discover_tools":
            # One ranked search for every provider. The native path's old rule
            # (every query word in one tool) found nothing for "die Jarvis
            # Agenten" and Jarvis told the user they did not exist (2026-09-20).
            from jarvis.live.discovery import discover

            try:
                offset = max(0, int(args.get("offset") or 0))
            except (TypeError, ValueError):  # a malformed offset starts the listing from the top
                offset = 0
            return discover(self.catalog(), str(args.get("query", "")), offset)
        if name == "task_status":
            return self._task_status(args)
        if name == "confirm_action":
            approval_id = str(args.get("approval_id", ""))
            if approval_id not in self._pending and len(self._pending) == 1:
                # One open question, so the yes can only mean it; a voice
                # model that mistypes the 36-character id must not void it.
                approval_id = next(iter(self._pending))
            pending = self._pending.get(approval_id)
            if pending is None or self.revision <= pending[3] or not self._user_approved():
                # Say why, or the model asks the same question again and again.
                return {
                    "success": False,
                    "executed": False,
                    "error": "This action has not been explicitly approved.",
                    "reason": "no pending approval"
                    if pending is None
                    else "the user's latest words are not a plain yes",
                    "approval_ids": list(self._pending),
                    "next_step": "Ask for a plain yes or no, then call confirm_action again.",
                }
            trace, _, _, _ = self._pending.pop(approval_id)
            from jarvis.core.model_selection import ModelSelection, use_operation_model

            if self.backend_model:
                with use_operation_model(
                    self.model_selection or ModelSelection("openai", self.backend_model)
                ):
                    result = await self.gateway.execute_confirmed(trace, self._request(trace))
            else:
                result = await self.gateway.execute_confirmed(trace, self._request(trace))
            return self._result(result)
        canonical = self._names.get(name, name)
        if name == "call_tool":
            canonical = str(args.get("name", ""))
            try:
                args = json.loads(args.get("arguments_json") or "{}")
            except ValueError:  # bad JSON is answered by the object check just below
                args = None
            if not isinstance(args, dict):
                return {
                    "success": False,
                    "executed": False,
                    "retryable": True,
                    "error": "arguments_json must be a JSON object. Correct it and call again.",
                }
        descriptor = next((d for d in self.catalog() if d.name == canonical), None)
        if descriptor is None:
            return {
                "success": False,
                "executed": False,
                "error": "Tool is no longer available. Discover the current catalog.",
            }
        import jsonschema  # type: ignore[import-untyped]

        try:
            jsonschema.validate(args, descriptor.input_schema)
        except jsonschema.ValidationError as exc:
            # Nothing ran yet, so the model may fix the argument and retry. A
            # bare "execution failed" left it guessing four times in a row.
            field = "/".join(str(part) for part in exc.absolute_path) or "arguments"
            return {
                "success": False,
                "executed": False,
                "retryable": True,
                "error": f"Invalid {field}: {exc.message[:300]}. Correct it and call again.",
            }
        trace = uuid4()
        from jarvis.core.model_selection import ModelSelection, use_operation_model

        if self.backend_model:
            with use_operation_model(
                self.model_selection or ModelSelection("openai", self.backend_model)
            ):
                result = await self.gateway.execute(canonical, args, self._request(trace))
        else:
            if canonical in {
                "computer_use",
                "computer-use",
                "dispatch_to_harness",
                "dispatch-to-harness",
            }:
                return {
                    "success": False,
                    "error": "Use screen_snapshot and desktop tools directly; "
                    "this voice model owns the action loop.",
                }
            result = await self.gateway.execute(canonical, args, self._request(trace))
        if result.error == VOICE_CONFIRM_SENTINEL:
            # A call that left its turn is still the user's order: its approval
            # question is kept and reaches them with the task's report. Only a
            # call nobody waits for any more is withdrawn.
            overtaken = revision != self.revision and call_id not in self._released
            if operation_token.is_cancelled() or overtaken:
                await self.gateway.cancel_pending(trace, reason="superseded")
                return {"success": False, "status": "superseded"}
            if not self.accepting:
                await self.gateway.cancel_pending(trace, reason="voice_session_closed")
                return {"success": False, "status": "voice_closed_before_confirmation"}
            approval_id = str(trace)
            self._pending[approval_id] = (trace, canonical, dict(args), self.revision)
            return {
                "success": False,
                "confirmation_required": True,
                "approval_id": approval_id,
                "tool": canonical,
                "arguments": args,
                "impact": result.output,
                "next_step": _APPROVAL_NEXT_STEP,
            }
        return self._result(result)

    @property
    def user_text(self) -> str:
        """The user's latest caption segment: what answers a question just asked."""
        return self._recent_user[-1] if self._recent_user else ""

    @user_text.setter
    def user_text(self, text: str) -> None:
        text = text or ""
        if (self._hangup_confirmation.pending_turn is not None
                and text.strip() and not confirms_hangup(text)
                and not user_asked_to_hang_up(text)):
            self._hangup_confirmation.reset()
        last = self._recent_user[-1] if self._recent_user else None
        if last is not None and (text.startswith(last) or last.startswith(text)):
            self._recent_user[-1] = text  # the same segment, transcribed further
        elif text.strip():
            self._recent_user = [*self._recent_user[-(_RECENT_SEGMENTS - 1) :], text]
        elif last is None:
            self._recent_user = [text]

    @property
    def request_text(self) -> str:
        """The user's last few segments together: what a tool was asked to do.

        The latest segment alone is often only the answer to Jarvis's question
        ("Ja, los"); a tool that checks its task against the user's words then
        sees nothing of the order and, in spawn_worker's bleed guard, even
        replaced the task with "Ja, los".
        """
        return " ".join(part.strip() for part in self._recent_user if part.strip())[
            -_REQUEST_TEXT_CHARS:
        ]

    def _reads_only(self, name: str, args: dict) -> bool:
        """A safe permission tier does not imply a read: internal sends are safe."""
        if name == "discover_tools":
            return True
        if name == "call_tool":
            name = str(args.get("name", ""))
            try:
                args = json.loads(args.get("arguments_json") or "{}")
            except (TypeError, ValueError):
                return False  # Unknown arguments cannot prove a read-only call.
        if name == "task_status":
            return isinstance(args, dict) and not str(args.get("cancel") or "").strip()
        canonical = self._names.get(name, name)
        descriptor = next((d for d in self.catalog() if d.name == canonical), None)
        if descriptor is None or not isinstance(args, dict):
            return False
        describe = getattr(descriptor, "describe_args", None)
        if callable(describe):
            try:
                return describe(args).get("level") == "read"
            except Exception:
                log.warning("Live tool impact inspection failed for %s", canonical, exc_info=True)
                return False
        return descriptor.risk_tier == "safe" and not descriptor.is_action_tool

    def _replay_call(self, name: str, args: dict) -> tuple[str, dict] | None:
        """Normalize aliases and wrappers without authorizing an operation."""
        if ":" in name:
            prefix, suffix = name.split(":", 1)
            if prefix.isidentifier() and (suffix in self._names or suffix in _BUILTIN_TOOLS):
                name = suffix
        if name == "call_tool":
            name = str(args.get("name", ""))
            try:
                args = json.loads(args.get("arguments_json") or "{}")
            except (TypeError, ValueError):
                return None  # Invalid arguments have no executable identity.
        name = self._names.get(name, name)
        return (name, args) if isinstance(args, dict) else None

    def steering_replay_key(self, name: str, args: dict) -> str | None:
        """Identity of an effect across replanning, independent of model call IDs.

        Session controls and reads cannot be reused this way. In particular,
        action approval and hang-up each require their own fresh consent.
        """
        call = self._replay_call(name, args)
        if call is None:
            return None
        name, args = call
        if name in _BUILTIN_TOOLS or self._reads_only(name, args):
            return None
        return json.dumps([name, args], sort_keys=True, ensure_ascii=False)

    def approval_effect_key(self, name: str, args: dict) -> str | None:
        """The pending effect's identity; the confirmation itself is never replayed."""
        call = self._replay_call(name, args)
        if call is None or call[0] != "confirm_action":
            return None
        pending = self._pending.get(str(call[1].get("approval_id", "")))
        if pending is None and len(self._pending) == 1:
            pending = next(iter(self._pending.values()))
        return self.steering_replay_key(pending[1], pending[2]) if pending else None

    def _user_approved(self) -> bool:
        """True when the latest user text is a short, unvetoed yes in any locale.

        The session language cannot pick the locale ("auto" resolves to English
        before anyone speaks), so every supported locale vets the answer: one
        must read it as a confirmation and none as a veto. Every word must be a
        go-ahead word, so an answer that adds a condition or a new instruction
        is not an approval of the old action.
        """
        from jarvis.voice.echo_confirmation import classify_response

        text = self.user_text
        words = re.sub(r"[^\w\s]", " ", text.casefold()).split()
        if not words or any(word not in _GO_AHEAD_WORDS for word in words):
            return False
        verdicts = {classify_response(text, language=locale) for locale in _APPROVAL_LOCALES}
        return "confirm" in verdicts and "veto" not in verdicts

    def _request(self, trace: UUID) -> SupervisorToolRequest:
        return SupervisorToolRequest(
            trace_id=trace,
            origin="realtime",
            user_utterance=self.request_text,
            cancel_token=self.cancel_token,
            config_snapshot={
                "output_language": self.language,
                "voice_confirm": True,
                "live_backend_model": self.backend_model,
                "live_session_id": self.session_id,
                "task_revision": self.revision,
                "workspace_user_utterance": self.user_text,
            },
        )

    @staticmethod
    def _result(result: Any) -> dict:
        from jarvis.core.redact import redact_secrets

        payload = {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "artifacts": list(getattr(result, "artifacts", ())),
            "verified": not (
                isinstance(result.output, dict) and result.output.get("verified") is False
            ),
        }
        images = take_images(payload)
        sanitized = json.loads(redact_secrets(json.dumps(payload, default=str)))
        sanitized["artifacts"].extend({**image, "type": "image"} for image in images)
        return sanitized

    async def close(self) -> None:
        from jarvis.core.image_references import get_store

        get_store().clear_scope("live:" + self.session_id)
        self.accepting = False
        await self._cancel_confirmations("voice_session_closed")

    async def _cancel_confirmations(self, reason: str) -> None:
        pending = tuple(self._pending.values())
        self._pending.clear()
        for trace, _, _, _ in pending:
            await self.gateway.cancel_pending(trace, reason=reason)
