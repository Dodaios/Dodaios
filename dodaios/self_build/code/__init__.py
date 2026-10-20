"""Coding projects for the self-building loop (``Kind.CODE``).

Dodaios knows the person's own repositories well enough to pick a suitable
issue now and then and ship it through their coding agent as a pull request:
rarely, proven by tests and CI, as a draft unless the person opted the
repository in to landing, and undoable with one click. Doc:
``docs/self-build-code.md``.

Modules: :mod:`.brief` (the stored project brief), :mod:`.intake` and
:mod:`.triage` (which issues), :mod:`.builder` (worktree, run, judge, pull
request), :mod:`.watch` (CI, merge, close, learning), :mod:`.loop` (the pass
and :func:`install`).
"""

from .loop import CodeLoop, install

__all__ = ["CodeLoop", "install"]
