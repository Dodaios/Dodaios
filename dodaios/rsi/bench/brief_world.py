"""The brief world of an installation's night: what a brief replay needs tonight.

Built with the first_move world (:mod:`dodaios.rsi.bench.lead_world`), from the
same CLI, platform, driver and :class:`~dodaios.rsi.budget.Budget`: the two
domains share one night's cap. Besides those it needs:

* **the lead's input to put a request into** (:class:`~.brief_replay.Template`):
  one recorded lead turn, pinned in ``bench.db`` and kept while that row exists
  and the lead runs on the same CLI and model. A replay result is reused only
  for the input it was measured on, and a comparison cut short by the budget
  carries on the next night; both need the input to stay put, and the newest
  turn changes with every message;
* **the repositories**: the person's clones, by repository id, from the folders
  the night's intake of past coding work read (``past_work.take_in``);
* **the repository at a task's commit** (:class:`Checkouts`): one scratch clone
  per repository under ``rsi/brief`` in the data folder, made with
  ``git clone --shared --no-checkout`` from the person's clone, so it borrows
  the objects and never touches that clone, its index, its branches or its
  worktrees. Each task moves it to its ``base`` commit (hooks and large-file
  downloads off); it is removed at the end of the night;
* **the kit** (:func:`kit_answer`): what ``delegate`` with ``options.prepare``
  answers in the app (``gate.kit_answer`` wrapped and rendered as the app's tool
  server renders it), built from the scratch clone for the lead's own wording.
  Nothing is written: the glossary's use counters stay as they are;
* **the lead's own look into the repository** (:func:`look_answer`): its
  read-only folder tools, run by the app's own code in the scratch clone; a
  path in the person's clone is read at the same place there, a path outside
  it is not answered.

Without a pinned input or a clone there is no brief world tonight, and the
night's report says why.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from .brief_replay import BriefWorld, Template, template_of
from .lead_replay import FirstMoveWorld
from .model import Task

__all__ = ["META_KEY", "Checkouts", "build", "kit_answer", "look_answer", "pinned_template"]

log = logging.getLogger(__name__)

#: Where the pinned template is kept in ``bench.db``'s meta table.
META_KEY: Final = "brief_template"
#: How many recorded turns are looked at for a template, newest first.
_LOOK_BACK: Final[int] = 50
#: How long a scratch clone's file index may take to build.
_INDEX_WAIT_S: Final[float] = 60.0
_GIT_TIMEOUT_S: Final[float] = 600.0


def pinned_template(bench: Any, turns: Any, *, cli: str, model: str) -> tuple[Template, int] | str:
    """The template brief replays are built on, and its turn's ``seq``; or why there is none."""
    meta = bench.get_meta(META_KEY) if bench is not None else {}
    seq = int(meta.get("seq") or 0)
    if seq:
        row = turns.turn(seq)
        if row is not None and row.cli == cli and row.model == model:
            found = template_of(str(row.system), str(row.message))
            if isinstance(found, Template):
                return found, seq
    for row in turns.turns(limit=_LOOK_BACK):
        if row.cli != cli or row.model != model:
            continue
        found = template_of(str(row.system), str(row.message))
        if isinstance(found, Template):
            if bench is not None and not bench.readonly:
                bench.set_meta(META_KEY, {"seq": int(row.seq), "digest": found.digest})
            return found, int(row.seq)
    return "no recorded lead turn on this model carries the standing lines"


def _clones(folders: Iterable[str | Path]) -> dict[str, Path]:
    from dodaios.rsi.repo_identity import repo_id

    found: dict[str, Path] = {}
    for folder in folders:
        path = Path(folder)
        if not path.is_dir():
            continue
        key = repo_id(path)
        if key and not key.startswith("path:"):
            found.setdefault(key, path)
    return found


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(  # noqa: S603 - fixed git argv, read-only on the person's clone
        ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.longpaths=true", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT_S,
        env=env,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class Checkouts:
    """One scratch clone per repository, moved to each task's commit; gone after the night."""

    def __init__(self, root: Path, clones: Mapping[str, Path]) -> None:
        self.root = Path(root)
        self.clones = dict(clones)
        self._lock = threading.Lock()

    def _scratch(self, repo: str) -> Path:
        return self.root / hashlib.sha256(repo.encode("utf-8")).hexdigest()[:12]

    def _clone(self, source: Path, dest: Path) -> str:
        common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], source)
        if common.returncode != 0 or not common.stdout.strip():
            return f"{source} is no git repository"
        dest.parent.mkdir(parents=True, exist_ok=True)
        made = _git(
            ["clone", "--quiet", "--shared", "--no-checkout", common.stdout.strip(), str(dest)]
        )
        if made.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)
            return "the repository could not be cloned for the replay"
        origin = _git(["remote", "get-url", "origin"], source).stdout.strip()
        if origin:
            # The same id as the person's clone, so the project's glossary applies.
            _git(["remote", "set-url", "origin", origin], dest)
        return ""

    def __call__(self, repo: str, base: str) -> Path | str:
        """The repository ``repo`` at commit ``base``, or why it cannot be had."""
        source = self.clones.get(repo)
        if source is None:
            return f"the repository {repo} is not on this machine"
        with self._lock:
            dest = self._scratch(repo)
            if not (dest / ".git").exists():
                failed = self._clone(source, dest)
                if failed:
                    return failed
            if _git(["cat-file", "-e", f"{base}^{{commit}}"], dest).returncode != 0:
                return "the commit the work started from is not in the local clone"
            moved = _git(["checkout", "--quiet", "--detach", "--force", base], dest)
            if moved.returncode != 0:
                return "the repository could not be moved to the commit the work started from"
            from dodaios.agentic_ide import file_index

            # The index of the commit before belongs to other files: build it again.
            file_index.forget_index(dest)
            file_index.prime_index(dest)
            return dest

    def close(self) -> None:
        """Remove the scratch clones. The person's clones were never touched."""
        with self._lock:
            shutil.rmtree(self.root, ignore_errors=True)


def _index_ready(folder: Path) -> None:
    from dodaios.agentic_ide import file_index

    stop_at = time.monotonic() + _INDEX_WAIT_S
    while file_index.cached_index(folder) is None and time.monotonic() < stop_at:
        time.sleep(0.1)


def kit_answer(task: Task, folder: Path, args: Mapping[str, Any]) -> str:
    """What ``delegate`` with ``options.prepare`` returns in the app, for the folder ``folder``.

    The kit is built as the app builds it for the lead's own wording (``task``
    of the call) and the person's words (the task's request), for the
    recipient the call names; the result is wrapped and rendered as the app's
    tool server renders a tool result.
    """
    from dodaios.brain.delegate_tool import _answer, parse_target  # noqa: PLC2701
    from dodaios.briefs import gate, handoff
    from dodaios.briefs import settings as brief_settings
    from dodaios.briefs.model import WRITER_LEAD, BriefDraft, Order, Recipient
    from dodaios.briefs.profiles import profile_for
    from dodaios.mcp.dodaios_tools_server import _render  # noqa: PLC2701

    raw = args.get("options")
    options: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    parsed = parse_target(args.get("target"))
    kind, ref = parsed if isinstance(parsed, tuple) else ("coding_agent", "")
    cli = str(options.get("cli") or (ref if kind == "coding_agent" else "") or "")
    model = str(options.get("model") or "")
    recipient = Recipient(
        kind="pane" if kind == "pane" else "coding_agent",
        cli=cli,
        model=model,
        effort=str(options.get("effort") or ""),
        folder=str(folder),
    )
    order = Order(
        writer=WRITER_LEAD,
        draft=BriefDraft(task=str(args.get("task") or "")),
        recipient=recipient,
        person_words=str(task.payload.get("request") or ""),
        wishes=handoff._wishes(),  # noqa: SLF001 - the person's standing wishes, read only
    )
    _index_ready(folder)
    data = gate.kit_answer(
        order,
        profiles=[profile_for(cli, model)],
        auto_effort=brief_settings.current().auto_effort,
        count_words=False,
    )
    target = f"{kind}:{ref}" if ref else kind
    return str(_render(_answer(target, "prepared", None, True, detail=data)))


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _rebase(raw: str, clone: Path, at: Path) -> str | None:
    """A path the lead named, moved from the person's clone to the scratch clone.

    ``None`` when it reaches outside the repository: a replay reads the
    repository at the task's commit and nothing else on the machine.
    """
    from dodaios.agent_chat.tools import resolve_path

    text = str(raw).strip()
    moved = text
    if text and Path(os.path.expanduser(text)).is_absolute():
        mine, root = _norm(text), _norm(str(clone))
        if mine != root and not mine.startswith(root + os.sep):
            return None
        rest = os.path.relpath(mine, root)
        moved = str(at) if rest == os.curdir else str(at / rest)
    found = _norm(str(resolve_path(at, moved)))
    base = _norm(str(at.resolve()))
    return moved if found == base or found.startswith(base + os.sep) else None


def look_answer(
    at: Path, clone: Path, tool: str, args: Mapping[str, Any]
) -> tuple[str, bool] | None:
    """What one of the lead's read-only folder tools answers in the repository at ``at``.

    The tool is the app's own (``agent_chat.tools``), run with the scratch
    clone as its folder; the lead's paths into its clone are read at the same
    place there, and the answer names its clone again. ``None`` when the call
    reaches outside the repository.
    """
    import asyncio

    from dodaios.agent_chat import tools as folder
    from dodaios.core.protocols import ToolResult
    from dodaios.mcp.dodaios_tools_server import _render  # noqa: PLC2701

    if tool not in folder.READ_ONLY_TOOLS:
        return None
    mapped: dict[str, Any] = {}
    for key, value in args.items():
        if key in ("path", "file_path") and isinstance(value, str):
            moved = _rebase(value, clone, at)
            if moved is None:
                return None
            mapped[key] = moved
        else:
            mapped[key] = value
    if "path" not in mapped and "file_path" not in mapped:
        mapped["path"] = str(at)  # the folder the lead had in mind: its clone
    output, error = asyncio.run(folder.execute_tool(tool, mapped, cwd=at))
    text = str(
        _render(ToolResult(success=not error, output=output, error=output if error else None))
    )
    for here, there in ((str(at), str(clone)), (at.as_posix(), clone.as_posix())):
        text = text.replace(here, there)
    return text, bool(error)


def build(
    first: FirstMoveWorld,
    *,
    home: Path,
    turns: Any,
    bench: Any,
    folders: Iterable[str | Path],
) -> BriefWorld | str:
    """Tonight's brief world on ``first``'s platform, driver and budget; or why there is none."""
    platform = first.platform
    pinned = pinned_template(bench, turns, cli=platform.cli, model=platform.model)
    if isinstance(pinned, str):
        return pinned
    template, _ = pinned
    clones = _clones(folders)
    if not clones:
        return "no repository of past coding work is on this machine"
    return BriefWorld(
        platform=replace(platform, base=template.digest),
        driver=first.driver,
        budget=first.budget,
        template=template,
        clones=clones,
        checkout=Checkouts(Path(home) / "rsi" / "brief", clones),
        kit=kit_answer,
        look=look_answer,
    )
