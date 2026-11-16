"""Look through what the second Assistant clip's window said for text that must not be in it.

    python scripts/readme_demo/clip-assistant2-ocr.py <take folder> [--text]

nodes-plugins-ocr.py reads the frames with macOS's own text recognition, which
a Linux computer does not have. This clip shows no plugin and no account, only
the app, a made-up bank export and the model's answer, so its window's own
words are enough: clip-assistant2-assistant.cjs writes the page's text at the
start, when the chart comes and at the end (take.json, notes.texts), and this
script looks through it for the computer's name, the home folder and login of
whoever records, the paths of the instance, and every value of DEMO_SCRUB. It
never prints a value it found, only where. ``--text`` prints every distinct
line, for a person to read through. Exits with 1 when something was found.
Look at the frames too: text drawn on a canvas is not in the page's text.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import socket
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__)
        return 2
    take = json.loads((Path(args[0]) / "take.json").read_text(encoding="utf-8"))
    texts = (take.get("notes") or {}).get("texts") or []
    if not texts:
        print("the take has no page text (notes.texts)", file=sys.stderr)
        return 2
    values = [
        socket.gethostname(),
        os.path.expanduser("~"),
        getpass.getuser(),
        "/home/user",
        "demo-assistant",
        "work-assistant",
    ]
    for pair in os.environ.get("DEMO_SCRUB", "").split(","):
        real = pair.split("=", 1)[0].strip()
        if real:
            values.append(real)
    values = [v for v in dict.fromkeys(values) if len(v) > 3 and v not in ("/root",)]
    # The home folder of root is "/root": looked for as a path, not as a word.
    patterns = [re.compile(re.escape(v), re.IGNORECASE) for v in values] + [
        re.compile(r"(?<![\w.])/root\b")
    ]
    found = 0
    for snap in texts:
        hits = [n for n, p in enumerate(patterns) if p.search(snap["text"])]
        print(
            f"{snap['when']:>6}: {len(snap['text'].splitlines())} lines, "
            + (f"FOUND value(s) #{hits}" if hits else "nothing found")
        )
        found += bool(hits)
    if "--text" in args:
        seen: dict[str, None] = {}
        for snap in texts:
            for line in snap["text"].splitlines():
                if line.strip():
                    seen.setdefault(line.strip(), None)
        print("every distinct line:")
        for line in seen:
            print("  " + line)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
