"""The brief world of an installation's round: what a brief replay needs.

Built with the first_move world (:mod:`dodaios.rsi.bench.lead_world`), from the
same CLI, platform, driver and :class:`~dodaios.rsi.budget.Budget`: the two
domains share one round's calls. Besides those it needs:

* **the lead's input to put a request into** (:class:`~.brief_replay.Template`):
  one recorded lead turn, pinned in ``bench.db`` and kept while that row exists
  and the lead runs on the same CLI and model. A replay result is reused only
  for the input it was measured on, and a comparison cut short by the budget
  carries on the next round; both need the input to stay put, and the newest
  turn changes with every message;
* **the repositories**: the person's clones, by repository id, from the folders
  the round's intake of past coding work read (``past_work.take_in``);
* **the repository at a task's commit** (:func:`commit_files`): read from the
  person's clone's own git objects (:class:`~.at_commit.CommitFiles`), at low
  priority and without a lock. Nothing is checked out and no file is written;
  the clone's working tree, index, branches and worktrees stay as they are;
* **the kit** (:func:`kit_answer`): what ``delegate`` with ``options.prepare``
  answers in the app (``gate.kit_answer`` wrapped and rendered as the app's tool
  server renders it), built from the commit for the lead's own wording. Nothing
  is written: the glossary's use counters stay as they are;
* **the lead's own look into the repository** (:func:`look_answer`): its
  read-only folder tools, answered at the commit as the app's tools answer on a
  checkout of it (:func:`~.at_commit.look`); a path outside the repository is
  not answered.

An earlier version moved one scratch checkout under ``rsi/brief`` in the data
folder to each task's commit, and wrote tens of thousands of files a round;
what such a version left behind is removed when the world is built.

Without a pinned input or a clone there is no brief world, and the round's
report says why.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from .at_commit import CommitFiles, look
from .brief_replay import BriefWorld, Template, template_of
from .lead_replay import FirstMoveWorld
from .model import Task

__all__ = ["META_KEY", "build", "commit_files", "kit_answer", "look_answer", "pinned_template"]

log = logging.getLogger(__name__)

#: Where the pinned template is kept in ``bench.db``'s meta table.
META_KEY: Final = "brief_template"
#: How many recorded turns are looked at for a template, newest first.
_LOOK_BACK: Final[int] = 50
#: Where an earlier version kept its scratch checkouts (removed when found).
_OLD_SCRATCH: Final = ("rsi", "brief")


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


def commit_files(clones: Mapping[str, Path], repo: str, base: str) -> CommitFiles | str:
    """The repository ``repo`` at commit ``base``, read in place; or why it cannot be had."""
    clone = clones.get(repo)
    if clone is None:
        return f"the repository {repo} is not on this machine"
    files = CommitFiles(clone, base)
    if not files.exists():
        return "the commit the work started from is not in the local clone"
    return files


def kit_answer(task: Task, files: CommitFiles, args: Mapping[str, Any]) -> str:
    """What ``delegate`` with ``options.prepare`` returns in the app, at ``files``' commit.

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
        folder=str(files.root),
    )
    order = Order(
        writer=WRITER_LEAD,
        draft=BriefDraft(task=str(args.get("task") or "")),
        recipient=recipient,
        person_words=str(task.payload.get("request") or ""),
        wishes=handoff._wishes(),  # noqa: SLF001 - the person's standing wishes, read only
    )
    data = gate.kit_answer(
        order,
        profiles=[profile_for(cli, model)],
        auto_effort=brief_settings.current().auto_effort,
        count_words=False,
        files=files,
    )
    target = f"{kind}:{ref}" if ref else kind
    return str(_render(_answer(target, "prepared", None, True, detail=data)))


def look_answer(files: CommitFiles, tool: str, args: Mapping[str, Any]) -> tuple[str, bool] | None:
    """What one of the lead's read-only folder tools answers at ``files``' commit.

    The text and whether it is an error; ``None`` when the call reaches outside
    the repository (:func:`~.at_commit.look`).
    """
    return look(files, tool, args)


def _remove_old_scratch(home: Path) -> None:
    """Remove the scratch checkouts an earlier version left in the data folder."""
    old = Path(home).joinpath(*_OLD_SCRATCH)
    if old.is_dir():
        log.info("self-improvement: removing the scratch checkouts of an earlier version")
        shutil.rmtree(old, ignore_errors=True)


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
    _remove_old_scratch(Path(home))
    clones = _clones(folders)
    if not clones:
        return "no repository of past coding work is on this machine"
    return BriefWorld(
        platform=replace(platform, base=template.digest),
        driver=first.driver,
        budget=first.budget,
        template=template,
        clones=clones,
        commit=lambda repo, base: commit_files(clones, repo, base),
        kit=kit_answer,
        look=look_answer,
    )
