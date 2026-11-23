"""Which assistant did this: the state a piece of work, or a benchmark run, was done in.

Two results can only be compared when they name what produced them. A
fingerprint lists everything that can make the same task come out differently:

* ``app`` the app version (an update changes what "as it ships" means);
* ``changes`` the learned changes in effect, by id;
* ``params`` a hash of the parameter values in effect;
* ``model``, ``seat``, ``cli`` what answered, where a model was asked.

Its ``id`` is a hash of all of them. Two runs with the same id ran on the same
assistant; a pair whose model or CLI differ is not a pair.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

__all__ = ["Fingerprint", "params_hash"]


def params_hash(values: Mapping[str, Any]) -> str:
    """A short hash of parameter values, independent of their order."""
    text = json.dumps(dict(values), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Fingerprint:
    app: str = ""
    changes: tuple[str, ...] = ()
    params: str = ""
    model: str = ""
    seat: str = ""
    cli: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "changes", tuple(sorted(set(self.changes))))

    @classmethod
    def of(
        cls,
        *,
        app: str = "",
        changes: Iterable[str] = (),
        params: Mapping[str, Any] | None = None,
        model: str = "",
        seat: str = "",
        cli: str = "",
    ) -> Fingerprint:
        return cls(
            app=app,
            changes=tuple(changes),
            params=params_hash(params or {}),
            model=model,
            seat=seat,
            cli=cli,
        )

    @property
    def id(self) -> str:
        text = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return "fp_" + hashlib.sha256(text.encode()).hexdigest()[:14]

    @property
    def platform(self) -> tuple[str, str, str]:
        """What answered. Both runs of a pair must agree on it."""
        return (self.model, self.seat, self.cli)

    def same_platform(self, other: Fingerprint) -> bool:
        return self.platform == other.platform and self.app == other.app

    def public(self) -> dict[str, Any]:
        return {"id": self.id, **asdict(self), "changes": list(self.changes)}
