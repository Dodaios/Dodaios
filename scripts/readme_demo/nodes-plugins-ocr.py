"""Read the text in a clip's frames and look for values that must not be in it.

    DEMO_SCRUB="real=stand-in,..." \
      python scripts/readme_demo/nodes-plugins-ocr.py <video.mp4> [--every 0.25] [--text]

The page helpers of the clips replace names in what a page draws (text,
attributes, field values), but not in what it paints on a canvas, and a model
can write a name it read from GitHub in a spelling nobody listed. So the clip
itself is read: ffmpeg takes a frame every ``--every`` seconds, macOS's own
text recognition (the Vision framework, loaded through PyObjC) reads it, and
every line is compared with the values of DEMO_SCRUB: each spelling (as
given, without accents, with German umlauts written out), without regard to
case, and also a word that differs from a value by one letter (a misread).

It prints, per frame, how many lines it read and where it found something
(the box, as a share of the frame), never the value. ``--text`` also prints
every distinct line it read, with the values replaced by [REAL], for a person
to read through. Exits with 1 when something was found. macOS only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


def spellings(value: str) -> set[str]:
    plain = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    written = value
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):  # i18n-allow: umlaut spellings to match, not German text
        written = written.replace(a, b)
    return {v.lower() for v in (value, plain, written) if v}


def near(a: str, b: str) -> bool:
    """One letter apart (replaced, missing or extra), for words of five letters or more."""
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1 :] == a for i in range(len(b)))


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__)
        return 2
    video = Path(args[0])
    every = float(args[args.index("--every") + 1]) if "--every" in args else 0.25
    show_text = "--text" in args

    values: list[str] = []
    for pair in os.environ.get("DEMO_SCRUB", "").split(","):
        real = pair.split("=", 1)[0].strip()
        if len(real) > 3:
            values.append(real)
    if not values:
        print("DEMO_SCRUB names no values to look for", file=sys.stderr)
        return 2
    exact = sorted({s for v in values for s in spellings(v)}, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(s) for s in exact), re.IGNORECASE)
    words = {w for s in exact for w in re.findall(r"[\w@.-]+", s) if len(w) >= 5}

    import objc  # noqa: PLC0415 - macOS only
    import Quartz  # noqa: F401,PLC0415 - gives PyObjC the CGRect type of a box
    from Foundation import NSURL  # noqa: PLC0415

    objc.loadBundle("Vision", globals(), bundle_path="/System/Library/Frameworks/Vision.framework")
    request_class = objc.lookUpClass("VNRecognizeTextRequest")
    handler_class = objc.lookUpClass("VNImageRequestHandler")

    found_frames = 0
    lines_seen: dict[str, None] = {}
    with tempfile.TemporaryDirectory(prefix="clip-ocr-") as work:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{every}", os.path.join(work, "%05d.png")],
            check=True,
        )
        frames = sorted(Path(work).glob("*.png"))
        for n, frame in enumerate(frames):
            request = request_class.alloc().init()
            request.setRecognitionLevel_(0)  # accurate
            request.setUsesLanguageCorrection_(False)
            handler = handler_class.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(frame)), {})
            # Without the framework's metadata PyObjC returns the bare result.
            done = handler.performRequests_error_([request], None)
            if not (done[0] if isinstance(done, tuple) else done):
                print(f"frame {n:04d}: not read")
                continue
            hits = []
            results = request.results() or []
            for observation in results:
                text = str(observation.topCandidates_(1)[0].string())
                lowered = text.lower()
                kind = ""
                if pattern.search(text):
                    kind = "exact"
                elif any(near(w, v) for w in re.findall(r"[\w@.-]+", lowered) for v in words):
                    kind = "similar"
                if kind:
                    (x, y), (w, h) = observation.boundingBox()
                    hits.append(f"{kind} at x={x:.2f} y={1 - y - h:.2f} w={w:.2f} h={h:.2f}")
                lines_seen.setdefault(pattern.sub("[REAL]", text), None)
            second = n * every
            if hits:
                found_frames += 1
                print(f"frame {n:04d} ({second:6.2f} s): {len(results)} lines, FOUND {len(hits)}: " + "; ".join(hits))
            else:
                print(f"frame {n:04d} ({second:6.2f} s): {len(results)} lines, nothing found")
    print(f"{len(frames)} frames read, {found_frames} with a finding")
    if show_text:
        print("every distinct line read (values replaced by [REAL]):")
        for line in lines_seen:
            print("  " + line)
    return 1 if found_frames else 0


if __name__ == "__main__":
    raise SystemExit(main())
