"""Type-ignore ratchet: per-file count of ``# type: ignore`` without an ``[error-code]``.

A bare ignore hides every error on its line, including ones introduced later.
``# type: ignore[attr-defined]`` is fine. Covered by
``tests/unit/ci/test_ratchet_gates.py``.
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet as r  # noqa: E402

_BARE = re.compile(r"#\s*type:\s*ignore(?!\s*\[)")


def count_source(source: str) -> int:
    try:
        comments = [
            t.string
            for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, IndentationError):
        comments = [ln for ln in source.splitlines() if "#" in ln]
    return sum(1 for c in comments if _BARE.search(c))


def scan() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in r.python_files("dodaios"):
        text = r.read_text(path)
        if "type:" not in text:
            continue
        n = count_source(text)
        if n:
            out[r.rel(path)] = n
    return out


def main(argv: list[str] | None = None) -> int:
    return r.run(
        "type-ignore",
        scan,
        "type-ignore-baseline.json",
        "ignores",
        "No new bare `# type: ignore` (without an error code) in dodaios/.",
        "fix the type error, or narrow the ignore to its code, "
        "e.g. `# type: ignore[attr-defined]`.",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
