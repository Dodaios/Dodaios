#!/usr/bin/env python3
"""A made-up raw take, to test the cut of voice_take.py without a person.

    <venv>/bin/python scripts/readme_demo/voice_take_synthetic.py OUTDIR [--cut] [--scale 1]

It draws, frame by frame at 60 frames a second, a stand-in of the chat page
(a dark page, one short exchange, the chat box) and plays a known story on
it: the pointer goes to the microphone and clicks it, a sentence spoken by
`say` drives the waveform, the square is clicked, "Transcribing...", the
words land in the box, Send, seven seconds of typing dots (the wait for a
model), a reply streams in, the pointer leaves and the window loses focus.
A notice with a made-up name and e-mail address stands in the corner for the
first seconds of the clip, so the privacy reading has something to find.

It writes OUTDIR/synthetic-raw.mkv (H.264 and AAC, like a real take),
OUTDIR/synthetic-truth.json (when everything happens) and
OUTDIR/synthetic-scrub.txt (the made-up name as a scrub pair). With --cut it
runs `voice_take.py cut` on the take into OUTDIR/out and checks what the cut
found against the truth. No app, screen or microphone is used.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 60
W, H = 1000, 620
SENTENCE = "Uh, give me three name ideas for a small coffee shop by the sea."
DELIVERED = "Give me three name ideas for a small coffee shop by the sea."
WARMUP = "From now on, answer me in two sentences unless I ask for more."
WARMUP_REPLY = "Got it: two sentences unless you ask for more."
ANSWER = ("Salt & Crema, The Driftwood Cup and Tide Pool Coffee. "
          "Want a tagline for one of them?")
FAKE_NAME = "Coralie Testperson"
FAKE_MAIL = "coralie@example.org"

PAGE = (21, 21, 23)
CAPTION = (27, 27, 30)
RAIL = (24, 24, 26)
BUBBLE_ME = (52, 52, 57)
BUBBLE_IT = (36, 36, 40)
INK = (236, 236, 238)
FAINT = (125, 125, 130)
GREEN = (62, 196, 104)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def speech_audio(workdir: Path) -> np.ndarray:
    aiff = workdir / "say.aiff"
    voice = ["-v", "Samantha"] if "Samantha" in subprocess.run(
        ["say", "-v", "?"], capture_output=True, text=True, check=False).stdout else []
    subprocess.run(["say", *voice, "-o", str(aiff), SENTENCE], check=True)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(aiff), "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    voice_pcm = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    loud = np.flatnonzero(np.abs(voice_pcm) > 0.01)
    voice_pcm = voice_pcm[loud[0]: loud[-1] + 1]  # spoken part only, so the truth is exact
    rms = math.sqrt(float(np.mean(voice_pcm ** 2)))
    return voice_pcm * (0.1 / max(rms, 1e-6))  # about -20 dBFS


#: full: the reply after seven seconds of typing dots; quick: after one second;
#: dictation: the words stay in the box and nothing is sent.
STORIES = ("full", "quick", "dictation")
NEVER = 1e9


def timeline(speech_len: float, story: str = "full") -> dict[str, float]:
    t: dict[str, float] = {"mic_click": 4.1, "speech_start": 4.6}
    t["speech_end"] = t["speech_start"] + speech_len
    t["stop_click"] = t["speech_end"] + 1.2
    t["text_lands"] = t["stop_click"] + 1.0
    if story == "dictation":
        t["send_click"] = t["answer_start"] = t["answer_end"] = NEVER
        settle = t["text_lands"]
    else:
        t["send_click"] = t["text_lands"] + 0.9
        t["answer_start"] = t["send_click"] + (7.0 if story == "full" else 1.0)
        t["answer_end"] = t["answer_start"] + 2.0
        settle = t["answer_end"]
    t["settle"] = settle
    t["pointer_leaves"] = settle + 2.5
    # A line of the app's own after the story: the clip must end before it.
    # (A dictation alone ends at the last change, so it gets none.)
    t["late_notice"] = settle + 2.8 if story != "dictation" else NEVER
    t["focus_lost"] = settle + 3.4
    t["end"] = settle + 4.8
    t["notice_from"], t["notice_to"] = 3.0, 4.6
    return t


class Page:
    """Draws one frame of the stand-in page for a given second."""

    def __init__(self, t: dict[str, float], levels: np.ndarray, scale: int) -> None:
        self.t, self.levels, self.s = t, levels, scale
        self.f13, self.f15, self.f12 = font(13 * scale), font(15 * scale), font(12 * scale)
        col_w = 680
        self.left = 64 + (W - 64 - col_w) // 2
        self.right = self.left + col_w
        self.box = (self.left, H - 96, self.right, H - 40)
        self.mic = (self.right - 70, H - 68)
        self.send = (self.right - 26, H - 68)
        self.stop = (self.right - 58, H - 68)  # the square at the pill's right end
        cx, cy = 560, 300
        self.path = [  # (time, x, y): the pointer's waypoints
            (0.0, cx, cy), (2.6, cx, cy), (3.6, *self.mic), (t["speech_end"] + 0.4, *self.mic),
            (t["speech_end"] + 1.0, *self.stop), (t["text_lands"] + 0.1, *self.stop),
        ]
        rest = (self.send[0] - 90, self.send[1] - 120)
        if t["send_click"] < NEVER:
            self.path += [(t["text_lands"] + 0.7, *self.send), (t["send_click"] + 0.5, *self.send),
                          (t["send_click"] + 1.1, *rest)]
        else:
            self.path += [(t["text_lands"] + 0.8, *rest)]
        self.path += [(t["pointer_leaves"], *rest), (t["pointer_leaves"] + 0.5, W + 40, 200)]

    def p(self, *values: float) -> list[int]:
        return [int(round(v * self.s)) for v in values]

    def pointer(self, now: float) -> tuple[float, float]:
        for (t0, x0, y0), (t1, x1, y1) in zip(self.path, self.path[1:]):
            if t0 <= now <= t1:
                k = ease((now - t0) / max(t1 - t0, 1e-6))
                return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
        return self.path[-1][1], self.path[-1][2]

    def level(self, now: float) -> float:
        i = int((now - self.t["speech_start"]) * FPS)
        return float(self.levels[i]) if 0 <= i < len(self.levels) else 0.0

    def text(self, d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fill: tuple[int, int, int],
             f: ImageFont.ImageFont) -> None:
        d.text(tuple(self.p(*xy)), text, fill=fill, font=f)

    def rrect(self, d: ImageDraw.ImageDraw, box: tuple[float, float, float, float], r: float,
              fill: tuple[int, int, int], outline: tuple[int, int, int] | None = None) -> None:
        d.rounded_rectangle(self.p(*box), radius=int(r * self.s), fill=fill, outline=outline, width=self.s)

    def frame(self, now: float) -> Image.Image:
        t, s = self.t, self.s
        img = Image.new("RGB", (W * s, H * s), PAGE)
        d = ImageDraw.Draw(img)
        focused = now < t["focus_lost"]
        # Caption, traffic lights, the switch in the middle.
        d.rectangle(self.p(0, 0, W, 44), fill=CAPTION)
        for k, color in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
            fill = color if focused else (78, 78, 82)
            d.ellipse(self.p(14 + 20 * k, 16, 26 + 20 * k, 28), fill=fill)
        self.rrect(d, (W / 2 - 90, 8, W / 2 + 90, 36), 14, (34, 34, 38))
        self.text(d, (W / 2 - 62, 14), "Dodaios     IDE", INK, self.f13)
        # The rail.
        d.rectangle(self.p(0, 44, 64, H), fill=RAIL)
        for k in range(6):
            self.rrect(d, (20, 70 + 52 * k, 44, 94 + 52 * k), 6, RAIL, outline=(70, 70, 74))
        # The exchange before the take.
        self.bubble(d, 66, WARMUP, mine=True)
        self.bubble(d, 116, WARMUP_REPLY, mine=False)
        # The message and the reply.
        if now >= t["send_click"]:
            k = ease((now - t["send_click"]) / 0.2)
            self.bubble(d, 176 + 8 * (1 - k), DELIVERED, mine=True)
            if t["send_click"] + 0.25 <= now < t["answer_start"]:
                self.rrect(d, (self.left, 232, self.left + 58, 266), 14, BUBBLE_IT)
                for n in range(3):
                    lift = 3 * max(0.0, math.sin(2 * math.pi * (now * 1.4 - n * 0.18)))
                    d.ellipse(self.p(self.left + 14 + 12 * n, 246 - lift, self.left + 20 + 12 * n, 252 - lift),
                              fill=(165, 165, 170))
            if now >= t["answer_start"]:
                words = ANSWER.split(" ")
                shown = int(len(words) * min(1.0, (now - t["answer_start"]) / (t["answer_end"] - t["answer_start"])))
                self.bubble(d, 232, " ".join(words[: max(1, shown)]), mine=False)
        # The chat box.
        self.rrect(d, self.box, 18, (30, 30, 33), outline=(52, 52, 56))
        self.text(d, (self.left + 16, H - 77), "+", FAINT, self.f15)
        recording = t["mic_click"] <= now < t["stop_click"]
        transcribing = t["stop_click"] <= now < t["text_lands"]
        typed = t["text_lands"] <= now < t["send_click"]
        if typed:
            self.text(d, (self.left + 40, H - 77), DELIVERED, INK, self.f15)
        else:
            hint = "Listening... speak now" if recording else "Ask anything..."
            self.text(d, (self.left + 40, H - 77), hint, FAINT, self.f15)
        if focused and not recording and int(now * 2) % 2 == 0:
            x = self.left + 40 + (d.textlength(DELIVERED, font=self.f15) / s if typed else 0)
            d.rectangle(self.p(x, H - 78, x + 1, H - 58), fill=INK)
        self.text(d, (self.right - 210, H - 75), "Claude Opus 5.5", FAINT, self.f13)
        if recording:
            self.pill(d, now)
        elif transcribing:
            self.rrect(d, (self.right - 170, H - 84, self.right - 42, H - 52), 16, (40, 40, 44), outline=(62, 62, 66))
            a = (now * 360 * 1.2) % 360
            d.arc(self.p(self.right - 160, H - 75, self.right - 146, H - 61), a, a + 270, fill=INK, width=2 * s)
            self.text(d, (self.right - 138, H - 76), "Transcribing...", INK, self.f13)
        else:
            mx, my = self.mic
            hover = math.dist(self.pointer(now), self.mic) < 18
            if hover:
                d.ellipse(self.p(mx - 18, my - 18, mx + 18, my + 18), fill=(46, 46, 50))
            d.rounded_rectangle(self.p(mx - 4, my - 9, mx + 4, my + 3), radius=4 * s, outline=FAINT, width=2 * s)
            d.arc(self.p(mx - 8, my - 4, mx + 8, my + 8), 0, 180, fill=FAINT, width=2 * s)
        sx, sy = self.send
        d.ellipse(self.p(sx - 18, sy - 18, sx + 18, sy + 18), fill=(236, 236, 238))
        if typed or recording or transcribing:
            d.line(self.p(sx, sy + 7, sx, sy - 7), fill=PAGE, width=3 * s)
            d.line(self.p(sx - 6, sy - 1, sx, sy - 7, sx + 6, sy - 1), fill=PAGE, width=3 * s)
        else:
            for k, hgt in enumerate((4, 9, 6, 10, 4)):
                d.line(self.p(sx - 8 + 4 * k, sy - hgt / 2, sx - 8 + 4 * k, sy + hgt / 2), fill=PAGE, width=2 * s)
        # A line of the app's own after the story: the clip must end before it.
        if t["late_notice"] <= now < t["late_notice"] + 1.0:
            self.rrect(d, (self.left, 330, self.left + 360, 372), 12, (40, 40, 44), outline=(66, 66, 70))
            self.text(d, (self.left + 16, 342), "2 updates from your assistant", FAINT, self.f13)
        # A notice with a made-up person in it, for the privacy reading.
        if t["notice_from"] <= now < t["notice_to"]:
            self.rrect(d, (W - 330, 56, W - 16, 96), 10, (44, 44, 48), outline=(70, 70, 74))
            self.text(d, (W - 318, 68), f"{FAKE_NAME} ({FAKE_MAIL}) joined", INK, self.f12)
        # The pointer.
        x, y = self.pointer(now)
        arrow = [(x, y), (x, y + 18), (x + 4.5, y + 14), (x + 8, y + 21), (x + 10.5, y + 20), (x + 7, y + 13),
                 (x + 13, y + 13)]
        d.polygon([tuple(self.p(px, py)) for px, py in arrow], fill=(250, 250, 250), outline=(0, 0, 0))
        return img

    def bubble(self, d: ImageDraw.ImageDraw, top: float, text: str, mine: bool) -> None:
        width = d.textlength(text, font=self.f15) / self.s
        lines = [text]
        if width > 520:  # two lines
            words, first = text.split(" "), []
            while words and d.textlength(" ".join([*first, words[0]]), font=self.f15) / self.s < 500:
                first.append(words.pop(0))
            lines = [" ".join(first), " ".join(words)]
            width = max(d.textlength(line, font=self.f15) / self.s for line in lines)
        x0 = self.right - width - 32 if mine else self.left
        self.rrect(d, (x0, top, x0 + width + 32, top + 16 + 22 * len(lines)), 16, BUBBLE_ME if mine else BUBBLE_IT)
        for n, line in enumerate(lines):
            self.text(d, (x0 + 16, top + 8 + 22 * n), line, INK, self.f15)

    def pill(self, d: ImageDraw.ImageDraw, now: float) -> None:
        t = self.t
        grow = ease((now - t["mic_click"]) / 0.15)
        x1, cy = self.right - 42, H - 68
        x0 = x1 - 148 * (0.9 + 0.1 * grow)
        self.rrect(d, (x0, cy - 16, x1, cy + 16), 16, (26, 37, 30), outline=(44, 96, 60))
        d.ellipse(self.p(x0 + 12, cy - 4, x0 + 20, cy + 4), fill=GREEN)
        for k in range(18):
            back = (17 - k) * 0.06
            value = self.level(now - back)
            half = 8 * (0.14 + 0.86 * value)
            x = x0 + 28 + 4 * k
            d.line(self.p(x, cy - half, x, cy + half), fill=GREEN, width=2 * self.s)
        seconds = int(max(0.0, now - t["mic_click"]))
        self.text(d, (x0 + 104, cy - 7), f"0:{seconds:02d}", FAINT, self.f12)
        sx = x1 - 16
        d.ellipse(self.p(sx - 12, cy - 12, sx + 12, cy + 12), fill=GREEN)
        d.rectangle(self.p(sx - 4, cy - 4, sx + 4, cy + 4), fill=PAGE)


def make(out: Path, scale: int, story: str) -> dict[str, float]:
    out.mkdir(parents=True, exist_ok=True)
    voice = speech_audio(out)
    t = timeline(len(voice) / 48000, story)
    total = t["end"]
    # The sound: room noise, the voice, a faint click per click, the Return at the end.
    rng = np.random.default_rng(7)
    sound = rng.normal(0, 0.0008, int(total * 48000)).astype(np.float32)
    at = int(t["speech_start"] * 48000)
    sound[at: at + len(voice)] += voice
    for when in (t["mic_click"], t["stop_click"], t["send_click"], t["end"] - 0.3):
        i = int(when * 48000)
        if i + 400 <= len(sound):
            sound[i: i + 400] += rng.normal(0, 0.02, 400).astype(np.float32)
    wav = out / "synthetic-sound.raw"
    wav.write_bytes((np.clip(sound, -1, 1) * 32767).astype(np.int16).tobytes())
    # The waveform follows the voice's loudness, like the app's level feed.
    frame_len = 48000 // FPS
    chunks = len(voice) // frame_len
    rms = np.sqrt(np.mean(voice[: chunks * frame_len].reshape(chunks, frame_len) ** 2, axis=1))
    levels = np.clip(rms / max(float(rms.max()), 1e-6), 0, 1)
    page = Page(t, levels, scale)
    raw = out / "synthetic-raw.mkv"
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W * scale}x{H * scale}",
         "-r", str(FPS), "-i", "-", "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", str(wav),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-g", str(FPS), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", "-f", "matroska", str(raw)],
        stdin=subprocess.PIPE,
    )
    assert enc.stdin is not None
    for n in range(int(total * FPS)):
        enc.stdin.write(page.frame(n / FPS).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("ffmpeg failed to write the synthetic take")
    wav.unlink()
    (out / "synthetic-scrub.txt").write_text(f"{FAKE_NAME}=Alex Rivera\n", encoding="utf-8")
    truth = {k: round(v, 3) for k, v in t.items()}
    (out / "synthetic-truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    return truth


def check(out: Path, truth: dict[str, float], story: str) -> int:
    script = Path(__file__).with_name("voice_take.py")
    cut_dir = out / "out"
    proc = subprocess.run([sys.executable, str(script), "cut", str(out / "synthetic-raw.mkv"), "--out", str(cut_dir),
                           "--port", "0", "--no-lock", "--scrub-file", str(out / "synthetic-scrub.txt")],
                          check=False)
    if proc.returncode != 0:
        print("FAIL: voice_take.py cut stopped")
        return 1
    report = json.loads((cut_dir / "voice-take.json").read_text(encoding="utf-8"))
    ev, cut = report["events"], report["cut"]
    results = []

    def near(name: str, got: float | None, want: float, tol: float) -> None:
        ok = got is not None and abs(got - want) <= tol
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name:<34} found {got}  expected {want:.2f} +- {tol}")

    near("voice starts", ev["sentence"][0], truth["speech_start"], 0.15)
    near("voice ends", ev["sentence"][1], truth["speech_end"], 0.2)
    near("microphone clicked", ev["microphone_clicked"], truth["mic_click"], 0.15)
    near("clip starts (click - 0.9 s)", cut["start"], truth["mic_click"] - 0.9, 0.2)
    def same(name: str, got: object, want: object) -> None:
        ok = got == want
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name:<34} found {got}  expected {want}")

    removed = cut["removed"]
    if story == "dictation":
        same("no message sent", ev["message_sent"], None)
        same("nothing cut out", removed, [])
        near("picture settles (words land)", ev["settled"], truth["text_lands"] + 0.1, 0.35)
        near("clip ends (+ 1.5 s)", cut["end"], truth["text_lands"] + 1.5, 0.3)
    else:
        near("message sent", ev["message_sent"], truth["send_click"], 0.2)
        if story == "full":
            near("reply arrives", ev["reply_arrives"], truth["answer_start"], 0.25)
            near("wait cut from (send + 0.9 s)", removed[0][0] if removed else None, truth["send_click"] + 0.9, 0.2)
            near("wait cut to (reply - 0.25 s)", removed[0][1] if removed else None,
                 truth["answer_start"] - 0.25, 0.25)
            same("exactly one wait cut out", len(removed), 1)
        else:
            same("quick reply: nothing cut out", removed, [])
        near("picture settles (reply end)", ev["settled"], truth["answer_end"] - 0.2, 0.35)
        near("clip ends (+ 1.5 s)", cut["end"], truth["answer_end"] + 1.3, 0.4)
        same("ends before the later notice", cut["end"] < truth["late_notice"], True)
    kinds = {f["kind"] for f in report["privacy"].get("findings", [])}
    want = {"name from the scrub list", "e-mail address"}
    seconds = sorted({f["second"] for f in report["privacy"].get("findings", [])})
    ok = want <= kinds and seconds and max(seconds) <= 2
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {'notice with name and mail found':<34} {sorted(kinds)} at {seconds} s")
    for name in ("voice-master.mp4", "voice-silent.mp4"):
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(cut_dir / name)],
            capture_output=True, text=True, check=True).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
        dur = float(info["format"]["duration"])
        good = (v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p" and v["r_frame_rate"] == "60/1"
                and has_audio == (name == "voice-master.mp4") and abs(dur - cut["length_s"]) < 0.15)
        results.append(good)
        print(f"{'PASS' if good else 'FAIL'}  {name:<34} {v['codec_name']} {v['pix_fmt']} {v['r_frame_rate']} "
              f"audio={has_audio} {dur:.2f} s (plan {cut['length_s']} s)")
    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--scale", type=int, default=1, help="2 draws at the pixel size of a Retina screen")
    parser.add_argument("--story", choices=STORIES, default="full", help="full (default): a wait of seven "
                        "seconds for the reply; quick: one second; dictation: nothing is sent")
    parser.add_argument("--cut", action="store_true", help="run voice_take.py cut on it and check the result")
    args = parser.parse_args()
    truth = make(args.out, args.scale, args.story)
    print(f"wrote {args.out / 'synthetic-raw.mkv'} ({truth['end']:.1f} s, story {args.story})")
    return check(args.out, truth, args.story) if args.cut else 0


if __name__ == "__main__":
    raise SystemExit(main())
