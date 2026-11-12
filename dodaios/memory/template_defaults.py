"""Values the first USER.md template filled in for every person.

Until November 2026 a new profile started with ``primary_language: de`` and
``timezone: Europe/Berlin``. Those were the maintainer's own, yet they read as
facts about whoever installed the app: in the prompt's "About the User" block,
on the profile page and, after the import, in the memory vault.

The template now leaves both empty. This module takes the old values back out
of a profile that still carries them unconfirmed. A value stays when the person
touched the field (an observation line names it) or when something of their own
supports it: the computer's clock follows that zone, or the language is among
the languages they said they speak.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from dodaios.memory.frontmatter import parse_frontmatter

log = logging.getLogger(__name__)

#: ``identity`` fields and the value the old template gave them.
LEGACY_DEFAULTS: Final[dict[str, str]] = {
    "primary_language": "de",
    "timezone": "Europe/Berlin",
}

#: Offsets are compared at this many instants, three months apart, so a zone
#: that only agrees in winter or only in summer does not count.
_SAMPLES: Final[int] = 4
_SAMPLE_STEP_S: Final[float] = 91 * 86400.0


def computer_follows(zone_name: str) -> bool | None:
    """True when this computer's clock keeps ``zone_name``'s time all year.

    ``None`` when that cannot be told (no zone database on this system).
    """
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(zone_name)
    except Exception:  # noqa: BLE001 - no tzdata or an unknown zone: cannot tell
        return None
    start = time.time()
    for i in range(_SAMPLES):
        ts = start + i * _SAMPLE_STEP_S
        try:
            local = datetime.fromtimestamp(ts).astimezone().utcoffset()
        except (OverflowError, OSError, ValueError):  # a platform without that instant
            return None
        if datetime.fromtimestamp(ts, tz=UTC).astimezone(zone).utcoffset() != local:
            return False
    return True


def _touched(body: str, field: str) -> bool:
    """True when the profile's own audit trail has a line for ``identity.<field>``."""
    pattern = rf"^-\s*\[\d{{4}}-\d{{2}}-\d{{2}}\]\s+identity\.{re.escape(field)}:"
    return re.search(pattern, body, re.MULTILINE | re.IGNORECASE) is not None


def assumed_fields(meta: dict[str, Any], body: str) -> tuple[str, ...]:
    """The identity fields that still hold the old template's value unconfirmed."""
    identity = meta.get("identity")
    if not isinstance(identity, dict):
        return ()
    out: list[str] = []
    for field, default in LEGACY_DEFAULTS.items():
        if identity.get(field) != default or _touched(body, field):
            continue
        if field == "timezone":
            if computer_follows(default) is False:
                out.append(field)
        else:
            languages = identity.get("languages")
            if not isinstance(languages, list) or default not in languages:
                out.append(field)
    return tuple(out)


def _frontmatter_end(text: str) -> int:
    """Offset just past the frontmatter's lines, or 0 when there is none."""
    if not text.startswith("---"):
        return 0
    closing = re.search(r"^---\s*$", text[3:], re.MULTILINE)
    return 3 + closing.start() if closing else 0


def clear_assumed(path: Path) -> tuple[str, ...]:
    """Empty the assumed fields in the USER.md at ``path``; return their names.

    Only the field's own line changes, so comments and every other value stay
    as they were. A file that does not read back as expected is left alone.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # no readable profile: nothing to repair
        return ()
    meta, body = parse_frontmatter(text)
    assumed = assumed_fields(meta, body)
    if not assumed:
        return ()

    end = _frontmatter_end(text)
    head, tail = text[:end], text[end:]
    for field in assumed:
        value = re.escape(LEGACY_DEFAULTS[field])
        line = rf"^([ \t]+{field}:[ \t]*)(['\"]?){value}\2(?=[ \t]*(?:#.*)?\r?$)"
        head = re.sub(line, r"\1null", head, count=1, flags=re.MULTILINE)

    new_meta, new_body = parse_frontmatter(head + tail)
    expected = {**meta, "identity": {**meta["identity"], **dict.fromkeys(assumed)}}
    if new_meta != expected or new_body != body:
        log.warning("USER.md: could not take the old template defaults out of %s", path)
        return ()

    fd, tmp_path = tempfile.mkstemp(prefix=".USER.md.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(head + tail)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:  # the temp file is already gone
            pass
        log.warning("USER.md: could not write %s", path, exc_info=True)
        return ()
    log.info(
        "USER.md: emptied %s; the old template had filled it in and the person never said it",
        ", ".join(f"identity.{name}" for name in assumed),
    )
    return assumed


__all__ = ["LEGACY_DEFAULTS", "assumed_fields", "clear_assumed", "computer_follows"]
