"""Credential handles: how a tool names a login without ever holding its value.

A handle is ``cred:<site>/<account>`` (``cred:github.com/owner``). The agent
and its tools pass the handle around; only the broker (broker.py) turns it
into values, inside the executor, at the last moment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["HANDLE_RE", "Handle", "find_handles", "parse_handle", "slug"]

_LABEL: Final[str] = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HANDLE_RE: Final[re.Pattern[str]] = re.compile(
    rf"\bcred:({_LABEL}(?:\.{_LABEL})+)/([A-Za-z0-9][A-Za-z0-9._@+-]{{0,63}})"
)


def slug(text: str) -> str:
    """``text`` as a short lowercase key: letters, digits and single dashes."""
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")[:48]


@dataclass(frozen=True, slots=True)
class Handle:
    domain: str
    account: str

    def __str__(self) -> str:
        return f"cred:{self.domain}/{self.account}"

    @property
    def placeholder_base(self) -> str:
        """The browser placeholder prefix: ``cred_github_com_owner``."""
        joined = re.sub(r"[^a-z0-9]+", "_", f"{self.domain}_{self.account}".casefold())
        return "cred_" + joined.strip("_")


def parse_handle(text: str) -> Handle | None:
    match = HANDLE_RE.fullmatch(str(text or "").strip())
    return Handle(match.group(1), match.group(2)) if match else None


def find_handles(text: str) -> list[Handle]:
    """Every distinct handle in ``text``, in order of first appearance."""
    seen: dict[Handle, None] = {}
    for match in HANDLE_RE.finditer(str(text or "")):
        seen.setdefault(Handle(match.group(1), match.group(2)), None)
    return list(seen)
