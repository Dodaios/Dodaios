"""Frontend escape-hatch ratchet: per-file counts of lint escapes in the web frontend.

Counted in ``dodaios/ui/web/frontend/src`` (tests excluded), as ``path::kind``:

* ``any``        explicit ``any`` (``: any``, ``as any``, ``<any>``),
* ``ts-ignore``  ``@ts-ignore`` / ``@ts-expect-error`` without a description,
* ``eslint``     ``eslint-disable`` without a reason (``-- why``).

The frontend has no ESLint setup, so this is a plain text scan (about a second).
Covered by ``tests/unit/ci/test_frontend_gates.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

FRONTEND = "dodaios/ui/web/frontend/src"

_ANY = re.compile(r":\s*any\b|\bas\s+any\b|<\s*any\s*[>,]|,\s*any\s*>")
_TS = re.compile(r"@ts-(?:ignore|expect-error)\b(.*)")
_ESLINT = re.compile(r"eslint-disable(?:-next-line|-line)?\b(.*)")
_COMMENT_START = ("//", "/*", "*")


def count_source(source: str) -> dict[str, int]:
    counts = {"any": 0, "ts-ignore": 0, "eslint": 0}
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_COMMENT_START) and _ANY.search(line.split("//")[0]):
            counts["any"] += 1
        m = _TS.search(line)
        if m and not re.sub(r"[\s:*/\-]+", "", m.group(1)):
            counts["ts-ignore"] += 1
        m = _ESLINT.search(line)
        if m and not re.search(r"--\s*\S", m.group(1).replace("*/", "")):
            counts["eslint"] += 1
    return {k: v for k, v in counts.items() if v}


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in r.walk_files(FRONTEND, (".ts", ".tsx")):
        if r.is_test_path(path) or path.name.endswith(".d.ts"):
            continue
        text = r.read_text(path)
        if "any" not in text and "ts-" not in text and "eslint" not in text:
            continue
        for kind, n in count_source(text).items():
            out[f"{r.rel(path)}::{kind}"] = n
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "frontend-escapes",
        scan,
        "frontend-escapes-baseline.json",
        "escapes",
        "No new explicit `any`, undescribed @ts-ignore/@ts-expect-error or reasonless "
        "eslint-disable in the frontend source.",
        "give the value a real type; write `// @ts-expect-error: why` or "
        "`// eslint-disable-next-line rule -- why` when an escape is unavoidable.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
