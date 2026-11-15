#!/usr/bin/env python3
"""Record the README's Telegram clip: a message from your phone, answered by the assistant.

    ~/Dodaios/.venv/bin/python scripts/readme_demo/telegram_take.py
    ~/Dodaios/.venv/bin/python scripts/readme_demo/telegram_take.py --dry-run [--fake-telegram]
    ~/Dodaios/.venv/bin/python scripts/readme_demo/telegram_take.py selftest
    ~/Dodaios/.venv/bin/python scripts/readme_demo/telegram_take.py cut phone|desktop RAW [options]
    ~/Dodaios/.venv/bin/python scripts/readme_demo/telegram_take.py stop

The clip shows Telegram as a real way to reach the assistant: a message typed
on a phone in the chat with the assistant's own bot, the assistant (Nova)
doing a small real task in a throwaway Dodaios instance, its answer in
Telegram, and the same conversation in the desktop app. Two recordings come
out of one take: the phone's own screen recording and the desktop app, filmed
by this script.

Step 1, on the Mac. Create a new bot for the demo with @BotFather in Telegram
(/newbot, name "Nova"), then run this script and paste the bot's token when it
asks. The token is not shown; it is kept in a file of the demo instance's
folder that only you can read, and handed to the instance in its environment
(never to the Keychain). The script checks the token with Telegram,
shows the bot's link, and prepares a throwaway instance on port 47993 with
sample projects and a short warm-up by the model, so the conversation on the
desk is already in use (the first time about five minutes). It never touches
your own Dodaios app, its data or its bot.

Step 2, on the phone. When the script beeps, press Return with the phone in
your hand; then: open the bot's link, tap Start, start the screen recording,
type and send

    Run the tests in trailhead and tell me if anything fails.

wait for the answer, stop the recording and AirDrop it to this Mac.

Everything else is done here. The desktop is filmed while the message arrives
and is answered (the DevTools screencast of a headless Chrome, 60 frames a
second, 1200 x 675 at scale 1.6). The script then waits for the AirDropped
video in ~/Downloads (only a file that is new since the take began), copies
it, and cuts both recordings by themselves: the start and the end of the
phone recording (the gestures that start and stop it), still waits of more
than about a second (a short dissolve), typing and scrolling at the speed
they were filmed. It writes into ~/Movies/Dodaios-Launch/v2/:

    telegram-phone-master.mp4     the phone, portrait, H.264, 60 fps, no sound
    telegram-desktop-master.mp4   the desktop, 1920 x 1080, H.264, 60 fps
    telegram-phone-sheet.png      one still per second of each clip
    telegram-desktop-sheet.png
    telegram-take.json            what happened when, and how it was cut
    telegram-notes.md             the same in words, with the privacy check
    telegram-raw/                 the raw recordings, for another cut

and prints the lines to hand to the lead. It stops the instance once the
answer has gone out and keeps the token, the warm-up and the pairing, so
another take needs neither BotFather nor the warm-up nor Start again: run the
same command. Every take starts from the state right after the warm-up, and
what was sent to the bot while no instance ran is marked read, not answered.

The Telegram sender's real names (read from the bot) are replaced in the
desktop's picture by "Alex Rivera" (only what is drawn), and both clips are
read by macOS's own text recognition for names, the account and computer
names and e-mail addresses. Findings name only the kind and the second.

--dry-run does all that needs no person: the instance, the warm-up, the
desktop filmed while a stand-in message enters through the instance's own chat
API (the call the Telegram bridge makes), and the phone cut on a made-up
portrait video. --fake-telegram sends that message through a local stand-in
for the Telegram Bot API instead, so the instance's real Telegram channel
pairs, receives and answers. `selftest` checks the channel without a model:
no token, a token Telegram rejects, pairing and a restart that keeps it.

Needs macOS, ffmpeg and ffprobe, Node.js and Google Chrome, Claude Code signed
in, and the Python of the Dodaios environment (numpy, Pillow, PyObjC).
Playwright is installed once into ~/Library/Caches/dodaios-demo-tools.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import getpass
import json
import math
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_DIR = Path.home() / "Movies" / "Dodaios-Launch" / "v2"
ROOT_DEFAULT = Path("/Users/Shared/tgdemo-root")
HOME_DEFAULT = Path("/Users/Shared/tgdemo")
PORT = 47993
#: The person's own app and the Dev app: only a read-only GET of the bot they
#: answer on, so that their bot is never used for the demo.
OWN_APPS = (47821, 47921)
SENTENCE = "Run the tests in trailhead and tell me if anything fails."
#: Sent in the warm-up, so the answer on the phone is short.
WARM_LINE = (
    "From now on, keep your answers to two sentences unless I ask for more. "
    "No need to tell me what you're about to do first."
)
ASSISTANT = "Nova"
MODEL_LABEL = "Claude Opus 5.5"
MODEL_ID = "claude-opus-5-5"
PERSONA = ("Alex", "Rivera", "alex")
TOOLS_CACHE = Path.home() / "Library" / "Caches" / "dodaios-demo-tools"
PLAYWRIGHT = "playwright@1.56"
WINDOW, SCALE, FPS = "1200x675", 1.6, 60
LOCK = Path("/tmp/dodaios-film.lock")  # noqa: S108 - the lock every recorder on this Mac uses
LOCK_WAIT = 300.0
MIN_FREE_BYTES = int(2.0 * 1024**3)
RAW_KEEP = 3
TELEGRAM_API = "https://api.telegram.org"
VIDEO_SUFFIXES = (".mov", ".mp4", ".m4v")
TOKEN_SHAPE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
#: The stand-in Bot API of --fake-telegram and selftest: a made-up bot and sender.
FAKE_TOKEN = "123456789:FAKEfakeFAKEfakeFAKEfakeFAKEfakeFAK"  # noqa: S105 - made up
FAKE_BOT = {
    "id": 123456789,
    "is_bot": True,
    "first_name": ASSISTANT,
    "username": "nova_demo_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
    "supports_inline_queries": False,
}
FAKE_OWNER = {
    "id": 770001234,
    "is_bot": False,
    "first_name": "Zebedee",
    "last_name": "Quince",
    "username": "zquince",
    "language_code": "en",
}
FAKE_STRANGER = {
    "id": 880005678,
    "is_bot": False,
    "first_name": "Orla",
    "username": "orla_x",
    "language_code": "en",
}
#: A fictional name drawn into the part of the made-up phone video that the
#: cut must remove; the privacy reading must find it in the raw and not in the clip.
TEST_NAME = "Zebedee Quince"

# The cut reads small gray frames, RATE a second. Areas are shares of the frame.
RATE = 20
PIXEL_STEP = 10  # gray levels: a message bubble on a dark page differs by more
LOCAL = {"desktop": 0.004, "phone": 0.0015}  # spinner, caret, clock: never progress
BIG = 0.012  # a message bubble appearing, share of the area above the message box
UPPER = 0.80  # the desktop's bubbles are looked for above the message box
APP_DIFF = 0.14  # phone: share of the title bar that differs where something covers it
MIN_STILL = 1.0  # seconds of still picture from which a wait is cut
# Kept around a cut, so that the still picture there lasts about a second: time
# to read what just came in (the message, the first sign of work).
KEEP_AFTER = 0.8  # seconds kept after a change, before a cut
KEEP_BEFORE = 0.25  # seconds kept before the picture moves on
DISSOLVE = 0.25
HOLD = 2.0  # seconds kept after the answer
LEAD = 0.7  # seconds shown before the first movement
END_STILL = 1.2  # the picture settles where it then stays still this long
SPEED_MAX = 1.25
# Measured like measure-hero.py, so the numbers compare with the other clips.
MEASURE_STEP, MEASURE_PIXELS = 12, 4

NAME_STOP = {
    "macbook",
    "air",
    "pro",
    "mac",
    "mini",
    "imac",
    "studio",
    "von",
    "van",
    "the",
    "and",
    "local",
    "dodaios",
    "assistant",
    "user",
    "admin",
    "nova",
    "telegram",
    "bot",
    "demo",
    "alex",
    "rivera",
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ALLOWED_EMAIL = re.compile(r"@example\.(com|org|net)$", re.IGNORECASE)

#: Secret values that must never reach the console (filled as they are known).
_SECRETS: list[str] = []


class Stop(Exception):
    """A step failed; the message says what to do."""


def _clean(text: str) -> str:
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "[token]")
    return text


def say(text: str = "") -> None:
    print(_clean(text), flush=True)


def item(label: str, value: str) -> None:
    say(f"  {label:<22} {value}")


def run(
    cmd: list[str], timeout: float | None = None, **kw: Any
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, timeout=timeout, check=False, **kw
    )


def wait_key(seconds: float) -> bool:
    """True when Return was pressed within ``seconds``."""
    if not sys.stdin or not sys.stdin.isatty():
        time.sleep(seconds)
        return False
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if ready:
        sys.stdin.readline()
        return True
    return False


def beep() -> None:
    sys.stdout.write("\a")
    sys.stdout.flush()


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def need_tools() -> None:
    for tool in ("ffmpeg", "ffprobe", "node", "git"):
        if shutil.which(tool) is None:
            raise Stop(
                f"{tool} is not on the PATH."
                + (" brew install ffmpeg" if tool.startswith("ff") else "")
            )
    missing = []
    for name in ("numpy", "PIL"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise Stop(
            "This Python lacks " + ", ".join(missing) + ". Run the script with the Python of "
            "the Dodaios environment, for example ~/Dodaios/.venv/bin/python."
        )


def ocr_available() -> bool:
    try:
        import objc  # noqa: F401
        import Quartz  # noqa: F401
        from Foundation import NSURL  # noqa: F401
    except ImportError:
        return False
    return True


def chrome_installed() -> bool:
    return Path("/Applications/Google Chrome.app").exists() or bool(shutil.which("google-chrome"))


def ensure_playwright() -> Path:
    """Playwright for Node in a cache folder outside the repository (installed once)."""
    modules = TOOLS_CACHE / "node_modules"
    if (modules / "playwright" / "package.json").exists():
        return modules
    say(f"  Installing Playwright once into {TOOLS_CACHE} (no browser download)")
    TOOLS_CACHE.mkdir(parents=True, exist_ok=True)
    package = TOOLS_CACHE / "package.json"
    if not package.exists():
        package.write_text(
            '{\n  "name": "dodaios-demo-tools",\n  "private": true\n}\n', encoding="utf-8"
        )
    env = dict(os.environ, PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1")
    proc = run(
        ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error", PLAYWRIGHT],
        timeout=600,
        cwd=str(TOOLS_CACHE),
        env=env,
    )
    if proc.returncode != 0 or not (modules / "playwright" / "package.json").exists():
        raise Stop("Playwright could not be installed: " + proc.stderr.strip()[-400:])
    return modules


def machine_state(folder: Path) -> tuple[float, int]:
    folder.mkdir(parents=True, exist_ok=True)
    return os.getloadavg()[0], shutil.disk_usage(folder).free


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------
# The Telegram Bot API (the demo bot only)
# --------------------------------------------------------------------------


class TelegramError(Exception):
    def __init__(self, code: int, text: str) -> None:
        super().__init__(text)
        self.code = code


class BotApi:
    """The few Bot API calls the script itself makes: getMe, getChat, and draining
    old updates while no instance polls. Never getUpdates while an instance runs."""

    def __init__(self, token: str, base: str = TELEGRAM_API) -> None:
        self.token, self.base = token, base.rstrip("/")

    def call(self, method: str, **params: Any) -> Any:
        url = f"{self.base}/bot{self.token}/{method}"
        data = None
        if params:
            data = urllib.parse.urlencode(
                {k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items()}
            ).encode()
        method = "POST" if data else "GET"
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
        body: dict[str, Any] | None = None
        failure: TelegramError | None = None
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                failure = TelegramError(exc.code, f"HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            failure = TelegramError(
                0, f"Telegram could not be reached ({type(exc).__name__}: {reason})"
            )
        if failure is not None:
            raise TelegramError(failure.code, self._safe(str(failure)))
        if not isinstance(body, dict) or not body.get("ok"):
            body = body if isinstance(body, dict) else {}
            raise TelegramError(
                int(body.get("error_code") or 0),
                self._safe(str(body.get("description") or "no answer")),
            )
        return body.get("result")

    def _safe(self, text: str) -> str:
        return text.replace(self.token, "[token]")

    def drain(self) -> int:
        """Mark every waiting update as read; how many there were.

        Only while no instance polls this bot: a message sent while it was off
        (a take that was given up) must not be answered when it starts again.
        """
        updates = self.call("getUpdates", timeout=0) or []
        if not updates:
            return 0
        last = max(int(u.get("update_id", 0)) for u in updates)
        self.call("getUpdates", offset=last + 1, timeout=0)
        return len(updates)


def own_app_bots() -> list[str]:
    """The bots the person's own Dodaios app and the Dev app answer on (read-only GETs)."""
    names = []
    for port in OWN_APPS:
        data = http_json(f"http://127.0.0.1:{port}/api/agent-chat/lead/channels", timeout=3)
        for row in (data or {}).get("channels") or []:
            if row.get("id") == "telegram" and row.get("handle"):
                names.append(str(row["handle"]).lstrip("@").lower())
    return names


def read_secret_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(tmp, path)


def check_token(token: str) -> dict[str, Any]:
    """getMe for ``token``; refuses the bot of the person's own app."""
    me = BotApi(token).call("getMe")
    username = str((me or {}).get("username") or "").lower()
    if not username:
        raise Stop("Telegram answered without a bot name; try the token again.")
    if username in own_app_bots():
        raise Stop(
            f"@{username} is the bot your own Dodaios app answers on. Two programs cannot read one "
            "bot: create a new bot for the demo with /newbot in @BotFather and paste its token."
        )
    return me


def obtain_token(paths: Paths, new: bool) -> tuple[str, dict[str, Any], bool]:
    """The demo bot's token, its getMe, and whether it is the one kept from an earlier take."""
    stored = "" if new else read_secret_file(paths.token_file)
    if stored:
        _SECRETS.append(stored)
        try:
            me = check_token(stored)
            item("bot", f"@{me['username']} (the token kept from the last take)")
            return stored, me, True
        except TelegramError as exc:
            if exc.code in (401, 404):
                say(
                    "  The kept token is no longer valid (Telegram says: "
                    + str(exc)
                    + "). Paste a new one."
                )
            else:
                raise Stop(f"Telegram could not check the bot: {exc}") from None
    if not sys.stdin or not sys.stdin.isatty():
        raise Stop("No token yet, and no terminal to paste one into. Run this in Terminal.")
    say('  In Telegram: @BotFather, /newbot, name it Nova, give it a username ending in "bot".')
    say("  BotFather answers with a token (digits, a colon, then about 35 characters).")
    for _ in range(3):
        token = getpass.getpass(
            "  Paste the token here (it is not shown) and press Return: "
        ).strip()
        if not token:
            continue
        _SECRETS.append(token)
        if not TOKEN_SHAPE.match(token):
            say("  That does not look like a bot token. Copy it again from BotFather's message.")
            continue
        try:
            me = check_token(token)
        except TelegramError as exc:
            if exc.code in (401, 404):
                say(
                    "  Telegram does not know this token ("
                    + str(exc)
                    + "). Copy it again: @BotFather, "
                    "/mybots, your bot, API Token."
                )
                continue
            raise Stop(f"Telegram could not check the token: {exc}") from None
        write_private(paths.token_file, token + "\n")
        item(
            "bot",
            f"@{me['username']} (the token is kept in {paths.token_file}, readable by you only)",
        )
        return token, me, False
    raise Stop("No valid token was pasted.")


# --------------------------------------------------------------------------
# A local stand-in for the Telegram Bot API (--fake-telegram, selftest)
# --------------------------------------------------------------------------


class FakeBotApi:
    """Answers the calls python-telegram-bot and this script make, for a made-up bot.

    getMe, deleteWebhook, getUpdates (a long poll), sendMessage, getChat. A test
    puts an update in with ``send_from``; what the bot sends is kept in ``sent``.
    """

    def __init__(self, token: str = FAKE_TOKEN) -> None:
        self.token = token
        self.lock = threading.Condition()
        self.updates: list[dict[str, Any]] = []
        self.next_update = 1
        self.next_message = 100
        self.sent: list[dict[str, Any]] = []
        self.calls: list[tuple[float, str]] = []
        self.users = {FAKE_OWNER["id"]: FAKE_OWNER, FAKE_STRANGER["id"]: FAKE_STRANGER}
        self.server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def start(self) -> FakeBotApi:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                self._answer({})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                kind = self.headers.get("Content-Type") or ""
                params: dict[str, Any] = {}
                if "json" in kind:
                    with contextlib.suppress(ValueError):
                        params = json.loads(raw.decode("utf-8") or "{}")
                elif "multipart" in kind:
                    for part in raw.split(b"\r\n--"):
                        head, _, value = part.partition(b"\r\n\r\n")
                        found = re.search(rb'name="([^"]+)"', head)
                        if found:
                            params[found.group(1).decode()] = value.rstrip(b"\r\n-").decode(
                                "utf-8", "replace"
                            )
                else:
                    params = {
                        k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()
                    }
                for key, value in list(params.items()):
                    if isinstance(value, str):
                        with contextlib.suppress(ValueError):
                            params[key] = json.loads(value)
                self._answer(params)

            def _answer(self, params: dict[str, Any]) -> None:
                path = urllib.parse.urlparse(self.path).path
                found = re.match(r"^/bot([^/]+)/(\w+)$", path)
                if not found:
                    return self._send(
                        404, {"ok": False, "error_code": 404, "description": "Not Found"}
                    )
                if found.group(1) != fake.token:
                    return self._send(
                        401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
                    )
                method = found.group(2)
                fake.calls.append((time.time(), method))
                result = fake.handle(method, params)
                if result is None:
                    return self._send(
                        400,
                        {
                            "ok": False,
                            "error_code": 400,
                            "description": f"Bad Request: method {method} is not in this stand-in",
                        },
                    )
                return self._send(200, {"ok": True, "result": result})

            def _send(self, code: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                with contextlib.suppress(OSError):
                    self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="fake-bot-api", daemon=True).start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            with self.lock:
                self.lock.notify_all()
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        if method == "getMe":
            return FAKE_BOT
        if method in ("deleteWebhook", "setMyCommands", "close", "logOut"):
            return True
        if method == "getWebhookInfo":
            return {
                "url": "",
                "has_custom_certificate": False,
                "pending_update_count": len(self.updates),
            }
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            wait = min(float(params.get("timeout") or 0), 25.0)
            end = time.time() + wait
            with self.lock:
                if offset:
                    self.updates = [u for u in self.updates if u["update_id"] >= offset]
                while not self.updates and time.time() < end and self.server is not None:
                    self.lock.wait(timeout=max(0.05, end - time.time()))
                return list(self.updates)
        if method == "sendMessage":
            self.next_message += 1
            chat_id = int(params.get("chat_id") or 0)
            message = {
                "message_id": self.next_message,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"},
                "from": FAKE_BOT,
                "text": str(params.get("text") or ""),
            }
            with self.lock:
                self.sent.append({"at": time.time(), "chat_id": chat_id, "text": message["text"]})
                self.lock.notify_all()
            return message
        if method == "getChat":
            user = self.users.get(int(params.get("chat_id") or 0))
            if user is None:
                return None
            return {
                k: v for k, v in user.items() if k in ("id", "first_name", "last_name", "username")
            } | {"type": "private"}
        return None

    def send_from(self, user: dict[str, Any], text: str) -> None:
        """A private message from ``user`` to the bot, as Telegram would deliver it."""
        with self.lock:
            update = {
                "update_id": self.next_update,
                "message": {
                    "message_id": self.next_update + 10,
                    "date": int(time.time()),
                    "chat": {
                        "id": user["id"],
                        "type": "private",
                        "first_name": user["first_name"],
                        **({"username": user["username"]} if "username" in user else {}),
                    },
                    "from": user,
                    "text": text,
                    **(
                        {
                            "entities": [
                                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
                            ]
                        }
                        if text.startswith("/")
                        else {}
                    ),
                },
            }
            self.next_update += 1
            self.updates.append(update)
            self.lock.notify_all()

    def sent_to(self, chat_id: int, after: float = 0.0) -> list[dict[str, Any]]:
        with self.lock:
            return [m for m in self.sent if m["chat_id"] == chat_id and m["at"] > after]


#: Put on the instance's PYTHONPATH for a test run only: points python-telegram-bot
#: at the stand-in above (no product code changes), then runs the sitecustomize
#: it hides (Homebrew's Python has one).
SHIM = r'''"""Test runs of telegram_take.py only: python-telegram-bot talks to a local stand-in."""
import importlib.abc
import importlib.machinery
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _run_hidden_sitecustomize():
    paths = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _HERE]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", paths)
    if spec is None or not spec.origin or os.path.dirname(os.path.abspath(spec.origin)) == _HERE:
        return
    with open(spec.origin, encoding="utf-8") as stream:
        code = compile(stream.read(), spec.origin, "exec")
    exec(code, {"__name__": "sitecustomize", "__file__": spec.origin, "__builtins__": __builtins__})


_run_hidden_sitecustomize()

_FAKE = os.environ.get("TGTAKE_FAKE_BOT_API", "").rstrip("/")
_REAL = "https://api.telegram.org/"


def _patch(module):
    bot = module.Bot
    signature = inspect.signature(bot.__init__)
    original = bot.__init__

    def __init__(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        for key in ("base_url", "base_file_url"):
            value = bound.arguments.get(key, signature.parameters[key].default)
            if isinstance(value, str) and value.startswith(_REAL):
                bound.arguments[key] = _FAKE + "/" + value[len(_REAL):]
        original(*bound.args, **bound.kwargs)

    bot.__init__ = __init__


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "telegram._bot":
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        run_module = spec.loader.exec_module

        def exec_module(module):
            run_module(module)
            _patch(module)

        spec.loader.exec_module = exec_module
        return spec


if _FAKE:
    sys.meta_path.insert(0, _Finder())
'''


# --------------------------------------------------------------------------
# The throwaway instance
# --------------------------------------------------------------------------


def http_json(
    url: str, *, timeout: float = 5, method: str = "GET", body: Any = None, origin: str = ""
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


@dataclass
class Paths:
    root: Path
    home: Path
    port: int
    out: Path
    downloads: Path

    @property
    def code(self) -> Path:
        return self.root / "code"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def config(self) -> Path:
        return self.state / "dodaios.toml"

    @property
    def warm(self) -> Path:
        return self.root / "warm"

    @property
    def secrets(self) -> Path:
        return self.root / "secrets"

    @property
    def token_file(self) -> Path:
        return self.secrets / "telegram-bot-token"

    @property
    def owner_file(self) -> Path:
        return self.secrets / "telegram-owner.json"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def pid_file(self) -> Path:
        return self.root / "instance.pid"

    @property
    def raw(self) -> Path:
        return self.out / "telegram-raw"

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def check_paths(paths: Paths) -> None:
    home = Path.home().resolve()
    for label, folder in (("--root", paths.root), ("--home", paths.home)):
        resolved = folder.resolve()
        if (
            resolved in (Path("/"), home)
            or REPO.resolve() in (resolved, *resolved.parents)
            or resolved in REPO.resolve().parents
        ):
            raise Stop(
                f"{label} {folder} must be a folder of its own, outside the repository"
                " and your home."
            )
    if paths.home.resolve() == paths.root.resolve():
        raise Stop("--home and --root must differ.")
    if paths.port in OWN_APPS:
        raise Stop(f"Port {paths.port} belongs to your own app; pick another with --port.")
    paths.root.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.root, 0o700)
    for folder in (paths.logs, paths.work):
        folder.mkdir(parents=True, exist_ok=True)


def code_commit(folder: Path) -> str:
    marker = folder / ".telegram-take-commit"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else ""


def ensure_code(paths: Paths, refresh: bool, bundle: Path | None = None) -> str:
    """A copy of the repository's committed code that stands still during the take.

    The repository may follow main by itself; a merge in the middle of a take
    would change the app under the instance. The built frontend bundle is
    cloned beside it (on APFS the clone takes no space).
    """
    commit = code_commit(paths.code)
    if (
        commit
        and not refresh
        and (paths.code / "dodaios" / "ui" / "web" / "dist" / "index.html").exists()
    ):
        return commit
    bundle = bundle or REPO / "dodaios" / "ui" / "web" / "dist"
    if not (bundle / "index.html").exists():
        raise Stop(
            f"No built frontend bundle in {bundle}. Build it first (npm run build in "
            "dodaios/ui/web/frontend), or name one with --bundle."
        )
    head = run(["git", "-C", str(REPO), "rev-parse", "HEAD"]).stdout.strip()
    if not head:
        raise Stop(f"{REPO} is not a git checkout.")
    shutil.rmtree(paths.code, ignore_errors=True)
    paths.code.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"],  # noqa: S603
        stdout=subprocess.PIPE,
    )
    untar = subprocess.run(
        ["tar", "-x", "-C", str(paths.code)],
        stdin=archive.stdout,  # noqa: S603
        capture_output=True,
        check=False,
    )
    archive.wait()
    if archive.returncode != 0 or untar.returncode != 0:
        raise Stop("Could not copy the code: " + untar.stderr.decode("utf-8", "replace")[-300:])
    target = paths.code / "dodaios" / "ui" / "web" / "dist"
    shutil.rmtree(target, ignore_errors=True)
    if run(["cp", "-cR", str(bundle), str(target)]).returncode != 0:
        if run(["cp", "-R", str(bundle), str(target)]).returncode != 0:
            raise Stop(f"Could not copy the frontend bundle from {bundle}.")
    (paths.code / ".telegram-take-commit").write_text(head + "\n", encoding="utf-8")
    return head


def pairing_window_s(paths: Paths) -> float:
    try:
        text = (paths.code / "dodaios" / "channels" / "base.py").read_text(encoding="utf-8")
        found = re.search(r"FIRST_CONTACT_PAIRING_WINDOW_S\s*=\s*([\d.]+)", text)
        if found:
            return float(found.group(1))
    except OSError:
        pass
    return 600.0


def instance_path() -> str:
    dirs: list[str] = []
    for tool in ("claude", "git", "node"):
        found = shutil.which(tool)
        if found:
            dirs.append(str(Path(found).parent))
    dirs += [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    seen: list[str] = []
    for folder in dirs:
        if folder not in seen and Path(folder).is_dir():
            seen.append(folder)
    return ":".join(seen)


@dataclass
class Telegram:
    """How the instance's Telegram channel runs: off, with the real bot, or the stand-in."""

    token: str = ""
    fake_url: str = ""
    shim: Path | None = None


class Instance:
    """The throwaway Dodaios on its own port, home folder and data folder."""

    def __init__(self, paths: Paths, python: str) -> None:
        self.paths, self.python = paths, python
        self.proc: subprocess.Popen[bytes] | None = None
        self.log: Path | None = None
        self.started_at = 0.0
        self.channel_since = 0.0

    # ---- the process ------------------------------------------------------

    def env(self, keep: bool, telegram: Telegram | None) -> dict[str, str]:
        user = getpass.getuser()
        python_path = [str(self.paths.code)]
        env = {
            "HOME": str(Path.home()),
            "USER": user,
            "LOGNAME": user,
            "PATH": instance_path(),
            "LANG": "en_US.UTF-8",
            "DEMO_PORT": str(self.paths.port),
            "DEMO_ROOT": str(self.paths.root),
            "DEMO_HOME": str(self.paths.home),
            "PYTHON": self.python,
        }
        if keep:
            env["DEMO_KEEP"] = "1"
        if telegram and telegram.token:
            # The token reaches the instance only here: not in a file of the
            # repository, not on a command line.
            env["TELEGRAM_BOT_TOKEN"] = telegram.token
            env["JARVIS__INTEGRATIONS__TELEGRAM__ENABLED"] = "true"
            if telegram.fake_url and telegram.shim is not None:
                env["TGTAKE_FAKE_BOT_API"] = telegram.fake_url
                python_path.append(str(telegram.shim))
        env["PYTHONPATH"] = ":".join(python_path)
        return env

    def start(self, *, keep: bool, telegram: Telegram | None = None, label: str = "") -> None:
        self.stop_leftover()
        if port_open(self.paths.port):
            raise Stop(f"Something else listens on port {self.paths.port}. Stop it, or use --port.")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log = self.paths.logs / f"instance-{stamp}{('-' + label) if label else ''}.log"
        script = self.paths.code / "scripts" / "readme_demo" / "demo-instance.sh"
        with self.log.open("wb") as log:
            self.proc = subprocess.Popen(  # noqa: S603
                ["/bin/bash", str(script)],
                env=self.env(keep, telegram),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd="/",
                start_new_session=True,
            )
        self.started_at = time.time()
        self.paths.pid_file.write_text(
            json.dumps(
                {"pid": self.proc.pid, "port": self.paths.port, "root": str(self.paths.root)}
            ),
            encoding="utf-8",
        )
        self.wait_ready()

    def wait_ready(self, timeout: float = 180.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self.proc is not None and self.proc.poll() is not None:
                raise Stop("The demo instance stopped while starting:\n" + self.log_tail(12))
            if http_json(self.url("/api/agent-chat/lead/channels"), timeout=3) is not None:
                return
            time.sleep(1.0)
        raise Stop(
            f"The demo instance did not answer within {timeout:.0f} s:\n" + self.log_tail(12)
        )

    def stop(self) -> None:
        pid = self.proc.pid if self.proc is not None else self._pid_from_file()
        if pid:
            self._end(pid)
        self.proc = None
        self.paths.pid_file.unlink(missing_ok=True)

    def stop_leftover(self) -> None:
        """An instance an earlier run of this script left running (its own folder only)."""
        pid = self._pid_from_file()
        if pid and self.proc is None:
            self._end(pid)
            self.paths.pid_file.unlink(missing_ok=True)

    def _pid_from_file(self) -> int:
        try:
            data = json.loads(self.paths.pid_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        pid = int(data.get("pid") or 0)
        command = run(["ps", "-o", "command=", "-p", str(pid)]).stdout if pid else ""
        # Only a process that is this instance: the launcher on this port.
        if "dodaios.ui.web.launcher" in command and f"--port {self.paths.port}" in command:
            return pid
        if "demo-instance.sh" in command:
            return pid
        return 0

    @staticmethod
    def _end(pid: int) -> None:
        try:
            group = os.getpgid(pid)
        except ProcessLookupError:
            return
        for sig, wait in ((signal.SIGTERM, 25.0), (signal.SIGKILL, 5.0)):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group, sig)
            end = time.time() + wait
            while time.time() < end:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)
                time.sleep(0.3)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def log_text(self, start: int = 0) -> str:
        if self.log is None or not self.log.exists():
            return ""
        with self.log.open("rb") as stream:
            stream.seek(start)
            return _clean(stream.read().decode("utf-8", "replace"))

    def log_size(self) -> int:
        return self.log.stat().st_size if self.log is not None and self.log.exists() else 0

    def log_tail(self, lines: int) -> str:
        return "\n".join("    " + line[:220] for line in self.log_text().splitlines()[-lines:])

    # ---- the app's API ----------------------------------------------------

    def url(self, route: str) -> str:
        return f"{self.paths.origin}{route}"

    def get(self, route: str, timeout: float = 8) -> Any:
        return http_json(self.url(route), timeout=timeout)

    def send(self, method: str, route: str, body: Any) -> Any:
        return http_json(
            self.url(route), timeout=30, method=method, body=body, origin=self.paths.origin
        )

    def lead(self) -> dict[str, Any]:
        lead = self.get("/api/agent-chat/lead")
        if not isinstance(lead, dict) or not lead.get("session_id"):
            raise Stop("The instance has no conversation with the assistant yet (setup not done?).")
        return lead

    def events(self, session_id: str, tail: int = 60) -> list[dict[str, Any]]:
        data = self.get(f"/api/agent-chat/sessions/{session_id}?tail={tail}")
        return list((data or {}).get("events") or [])

    def telegram_row(self) -> dict[str, Any]:
        for row in (self.get("/api/agent-chat/lead/channels") or {}).get("channels") or []:
            if row.get("id") == "telegram":
                return row
        return {}

    def wait_channel(self, timeout: float = 120.0) -> dict[str, Any]:
        """The Telegram row once Telegram has named the bot to the live channel."""
        end = time.time() + timeout
        while time.time() < end:
            row = self.telegram_row()
            if row.get("connected"):
                self.channel_since = time.time()
                return row
            failed = channel_failures(self.log_text())
            if failed:
                raise Stop("The instance's Telegram channel did not start: " + failed[-1][:300])
            if not self.alive():
                raise Stop("The demo instance stopped:\n" + self.log_tail(12))
            time.sleep(1.0)
        raise Stop(f"The Telegram channel was not up after {timeout:.0f} s:\n" + self.log_tail(10))

    def owner_ids(self) -> list[int]:
        try:
            import tomllib

            data = tomllib.loads(self.paths.config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        ids = (
            ((data.get("integrations") or {}).get("telegram") or {}).get("allowed_user_ids")
        ) or []
        return [int(v) for v in ids if str(v).lstrip("-").isdigit()]

    def wait_settled(
        self, session_id: str, after_seq: int, timeout: float = 600.0, calm: float = 6.0
    ) -> list[dict[str, Any]]:
        """Wait until the lead's turns after ``after_seq`` are over and nothing runs."""
        end = time.time() + timeout
        idle_since = 0.0
        while time.time() < end:
            lead = self.get("/api/agent-chat/lead") or {}
            running = bool(lead.get("running"))
            threads = (self.get("/api/agent-chat/sessions?surface=agent") or {}).get(
                "sessions"
            ) or []
            running = running or any(t.get("running") for t in threads)
            if running:
                idle_since = 0.0
            elif not idle_since:
                idle_since = time.time()
            elif time.time() - idle_since >= calm:
                return [e for e in self.events(session_id, 200) if e["seq"] > after_seq]
            time.sleep(1.0)
        raise Stop(f"The assistant was still working after {timeout / 60:.0f} minutes.")


def channel_failures(log: str) -> list[str]:
    """Why the instance's Telegram channel did not start, as its log says (redacted there).

    The server's own summary line carries the reason; the channel manager's
    line comes through only when the standard logging reaches the console.
    """
    found = [
        m.strip()
        for m in re.findall(r"Telegram-Channel disabled \((.+)\)\s*$", log, re.MULTILINE)
        if m.strip() != "config off"
    ]
    found += [m.strip() for m in re.findall(r"Channel 'telegram' start failed: (.*)", log)]
    return found


def set_owner(config: Path, user_id: int) -> None:
    """Put the paired Telegram user back into the instance's own config (a retry)."""
    import tomlkit

    doc = (
        tomlkit.parse(config.read_text(encoding="utf-8")) if config.exists() else tomlkit.document()
    )
    integrations = doc.get("integrations")
    if integrations is None:
        integrations = tomlkit.table()
        doc["integrations"] = integrations
    telegram = integrations.get("telegram")
    if telegram is None:
        telegram = tomlkit.table()
        integrations["telegram"] = telegram
    ids = [int(v) for v in (telegram.get("allowed_user_ids") or [])]
    if user_id not in ids:
        telegram["allowed_user_ids"] = [*ids, user_id]
    config.write_text(tomlkit.dumps(doc), encoding="utf-8")


def save_warm(paths: Paths, info: dict[str, Any]) -> None:
    shutil.rmtree(paths.warm, ignore_errors=True)
    paths.warm.mkdir(parents=True)
    for source, name in ((paths.home, "home"), (paths.state, "state")):
        if run(["cp", "-cpR", str(source), str(paths.warm / name)]).returncode != 0:
            if run(["cp", "-pR", str(source), str(paths.warm / name)]).returncode != 0:
                raise Stop(f"Could not keep a copy of {source}.")
    (paths.warm / "warm.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def warm_info(paths: Paths) -> dict[str, Any] | None:
    try:
        return json.loads((paths.warm / "warm.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def restore_warm(paths: Paths) -> None:
    """The instance as it was right after the warm-up (a take used it since)."""
    for target, name in ((paths.home, "home"), (paths.state, "state")):
        shutil.rmtree(target, ignore_errors=True)
        if run(["cp", "-cpR", str(paths.warm / name), str(target)]).returncode != 0:
            if run(["cp", "-pR", str(paths.warm / name), str(target)]).returncode != 0:
                raise Stop(f"Could not restore {target} from the warm-up copy.")


def scrub_logs(paths: Paths, token: str) -> int:
    """Lines of the instance's logs that held the token (rewritten without it)."""
    if not token:
        return 0
    found = 0
    needle = token.encode("utf-8")
    for folder in (paths.logs, paths.state / "data" / "logs", paths.work):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() in (".jpg", ".png", ".mp4", ".mov", ".db")
                or path.stat().st_size > 300 * 1024**2
            ):
                continue
            data = path.read_bytes()
            if needle in data:
                found += data.count(needle)
                path.write_bytes(data.replace(needle, b"[token]"))
    return found


# --------------------------------------------------------------------------
# Node scripts: the warm-up (record.cjs) and the desktop filming
# --------------------------------------------------------------------------


def node_env(paths: Paths, modules: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("JARVIS", "DODAIOS", "CLAUDE_CODE", "TELEGRAM"))
    }
    env.update(
        {"NODE_PATH": str(modules), "DEMO_BROWSER": "chrome", "DEMO_URL": paths.origin + "/"}
    )
    env.update(extra or {})
    return env


def run_record_cjs(paths: Paths, modules: Path, parts: str, folder: Path) -> None:
    """record.cjs's own setup and warm-up, not filmed."""
    env = node_env(
        paths, modules, {"DEMO_PARTS": parts, "DEMO_NAME": ASSISTANT, "DEMO_MODEL": MODEL_LABEL}
    )
    folder.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["node", str(HERE / "record.cjs"), str(folder)],
        env=env,  # noqa: S603
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    tail: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-12:]
        if line:
            say(f"    {line[:160]}")
    if proc.wait() != 0:
        raise Stop(
            "The setup or warm-up stopped (record.cjs). Its last lines are above; its "
            f"screenshots are in {folder}."
        )


class Film:
    """telegram-film.cjs in its own process, steered one line at a time."""

    def __init__(self, paths: Paths, modules: Path, folder: Path, scrub_file: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        env = node_env(
            paths,
            modules,
            {
                "DEMO_WINDOW": WINDOW,
                "DEMO_SCALE": str(SCALE),
                "DEMO_FPS": str(FPS),
                "DEMO_SCRUB_FILE": str(scrub_file),
            },
        )
        self.proc = subprocess.Popen(  # noqa: S603
            ["node", str(HERE / "telegram-film.cjs"), str(folder)],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=(folder / "film.log").open("w"),
            text=True,
            bufsize=1,
        )
        self.expect("ready", 120)

    def expect(self, word: str, timeout: float) -> str:
        assert self.proc.stdout is not None
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([self.proc.stdout], [], [], max(0.05, end - time.time()))
            if not ready:
                continue
            line = self.proc.stdout.readline()
            if not line:
                raise Stop(f"The desktop filming stopped (see {self.folder / 'film.log'}).")
            line = line.strip()
            if line.startswith("error"):
                raise Stop("The desktop filming failed: " + line[6:])
            if line.split(" ")[0] == word:
                return line
        raise Stop(f"The desktop filming did not answer ({word}).")

    def command(self, line: str, answer: str, timeout: float = 30) -> str:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return self.expect(answer, timeout)

    def stop(self) -> None:
        if self.proc.poll() is None:
            with contextlib.suppress(Stop, BrokenPipeError, OSError):
                self.command("stop", "stopped", 60)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=20)
        if self.proc.poll() is None:
            self.proc.kill()


class FilmLock:
    """The lock other recorders on this Mac use while they film or render."""

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name, self.enabled, self.held = name, enabled, False

    def take(self) -> None:
        if not self.enabled or self.held:
            return
        waited, told = 0.0, False
        while waited < LOCK_WAIT:
            try:
                LOCK.mkdir()
            except FileExistsError:
                if not told:
                    owner = (
                        (LOCK / "owner").read_text(encoding="utf-8").strip()
                        if (LOCK / "owner").exists()
                        else "?"
                    )
                    say(f"  Another recording on this Mac is filming ({owner}); waiting for it.")
                    told = True
                time.sleep(2)
                waited += 2
                continue
            (LOCK / "owner").write_text(self.name, encoding="utf-8")
            self.held = True
            return
        say("  The other recording still films; going on without waiting.")

    def release(self) -> None:
        if self.held:
            shutil.rmtree(LOCK, ignore_errors=True)
            self.held = False


# --------------------------------------------------------------------------
# Reading a recording
# --------------------------------------------------------------------------


def probe(path: Path) -> dict[str, Any]:
    out = run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    ).stdout
    try:
        data = json.loads(out or "{}")
    except ValueError:
        data = {}
    fmt = data.get("format") or {}
    info: dict[str, Any] = {
        "duration": float(fmt.get("duration") or 0),
        "start": float(fmt.get("start_time") or 0),
        "video": None,
        "audio": None,
    }
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind in ("video", "audio") and info[kind] is None:
            info[kind] = stream
    return info


def frame_rates(path: Path) -> dict[str, Any]:
    """How the frames of a recording really come: their count, the mean and the
    longest gap (a phone records only when its screen changes)."""
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            str(path),
        ]
    ).stdout
    times = sorted(float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", out))
    if len(times) < 2:
        return {"frames": len(times)}
    gaps = [b - a for a, b in zip(times, times[1:], strict=False) if b > a]
    span = times[-1] - times[0]
    return {
        "frames": len(times),
        "mean_fps": round((len(times) - 1) / max(span, 1e-6), 1),
        "longest_gap_s": round(max(gaps), 3) if gaps else 0.0,
        "variable": bool(gaps) and max(gaps) > 1.5 * min(gaps) + 0.002,
    }


def shown_size(path: Path) -> tuple[int, int]:
    """The size the picture is shown at (a stored rotation applied)."""
    with tempfile.TemporaryDirectory(prefix="tgtake-") as tmp:
        png = Path(tmp) / "f.png"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-frames:v", "1", str(png)])
        if not png.exists():
            raise Stop(f"{path} has no readable picture.")
        from PIL import Image

        with Image.open(png) as image:
            return image.size


@dataclass
class Footage:
    path: Path
    kind: str  # "phone" | "desktop"
    duration: float
    frames: Any  # numpy uint8 [n, h, w], RATE a second
    size: tuple[int, int]
    t0: float = 0.0

    @property
    def last(self) -> int:
        return len(self.frames) - 1

    def time(self, index: int) -> float:
        return self.t0 + index / RATE

    def index(self, seconds: float) -> int:
        return max(0, min(self.last, int(round((seconds - self.t0) * RATE))))

    def diff(
        self,
        i: int,
        j: int,
        rows: tuple[int, int] | None = None,
        cols: tuple[int, int] | None = None,
    ) -> float:
        """Share of the pixels that differ between two frames (of a part of them, if given)."""
        import numpy as np

        a, b = self.frames[i], self.frames[j]
        if rows:
            a, b = a[rows[0] : rows[1]], b[rows[0] : rows[1]]
        if cols:
            a, b = a[:, cols[0] : cols[1]], b[:, cols[0] : cols[1]]
        return float(np.count_nonzero((np.maximum(a, b) - np.minimum(a, b)) > PIXEL_STEP)) / max(
            1, a.size
        )


def read_footage(path: Path, kind: str) -> Footage:
    import numpy as np

    info = probe(path)
    if not info["video"]:
        raise Stop(f"{path} has no picture.")
    w, h = shown_size(path)
    width = 320 if w >= h else 180
    height = max(2, int(round(width * h / w / 2)) * 2)
    raw = subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-vf",
            f"fps={RATE},scale={width}:{height}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8)
    count = frames.size // (width * height)
    if count < 4:
        raise Stop(f"{path} is too short to cut.")
    return Footage(
        path=path,
        kind=kind,
        duration=info["duration"],
        frames=frames[: count * width * height].reshape(count, height, width),
        size=(w, h),
    )


def still_runs(f: Footage, lo: int, hi: int) -> list[tuple[int, int]]:
    """Stretches in which the picture stays as it was (``a`` to ``b``, frame
    indexes; ``b`` is the first frame that moved on, or ``hi + 1``)."""
    local = LOCAL[f.kind]
    need = int(round(MIN_STILL * RATE))
    runs: list[tuple[int, int]] = []
    a = lo
    while a < hi:
        j = a + 1
        while j <= hi and f.diff(j, a) <= local:
            j += 1
        if j - a >= need:
            runs.append((a, j))
            a = j
        else:
            a += 1
    return runs


def change_begins(f: Footage, a: int, b: int) -> int:
    """Where the change that ended a still stretch began: a message that comes in
    line by line first changes only a little."""
    import numpy as np

    if b > f.last:
        return b
    calm = max(f.diff(k, a) for k in range(a, min(b, a + RATE)))
    level = max(calm * 1.5, calm + 0.0006)
    k = b
    while k > a + 1 and f.diff(k - 1, a) > level:
        k -= 1
    del np
    return k


def removals(f: Footage, lo: int, hi: int) -> list[tuple[float, float]]:
    """The waits to cut out between ``lo`` and ``hi`` (seconds of the recording)."""
    out: list[tuple[float, float]] = []
    for a, b in still_runs(f, lo, hi):
        if b > hi:
            continue  # the end of the clip is cut by the end rule
        k = change_begins(f, a, b)
        r0, r1 = f.time(a) + KEEP_AFTER, f.time(k) - KEEP_BEFORE
        if r1 - r0 >= 0.5:
            out.append((r0, r1))
    return out


def settled_after(f: Footage, start: int) -> int:
    """The first frame from ``start`` on after which the picture stays still for END_STILL."""
    need = int(round(END_STILL * RATE))
    local = LOCAL[f.kind]
    g = start
    while g < f.last:
        j = g + 1
        while j <= f.last and f.diff(j, g) <= local:
            j += 1
        if j > f.last or j - g >= need:
            return g
        g = j
    return f.last


@dataclass
class Plan:
    start: float
    end: float
    removed: list[tuple[float, float]]
    speed: float = 1.0
    events: dict[str, Any] = field(default_factory=dict)

    @property
    def segments(self) -> list[tuple[float, float]]:
        out, at = [], self.start
        for r0, r1 in self.removed:
            out.append((at, r0))
            at = r1
        out.append((at, self.end))
        return out

    @property
    def length(self) -> float:
        return (sum(e - s for s, e in self.segments) - DISSOLVE * len(self.removed)) / self.speed


def clean_removed(
    removed: list[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for r0, r1 in sorted(removed):
        r0, r1 = max(r0, start + 0.5), min(r1, end - 0.5)
        if out and r0 < out[-1][1] + 0.5:
            continue
        if r1 - r0 >= 0.5:
            out.append((r0, r1))
    return out


def title_strips(path: Path, rate: int = 10, width: int = 540) -> Any:
    """The middle of a phone recording's title bar (where a chat shows its name),
    sharp enough to read letters: gray, ``rate`` a second, the frame ``width`` wide."""
    import numpy as np

    w, h = shown_size(path)
    height = max(2, int(round(width * h / w / 2)) * 2)
    top, bottom = int(height * 0.056), int(height * 0.115)
    left, right = int(width * 0.22), int(width * 0.78)
    sw, sh = right - left, bottom - top
    raw = subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-vf",
            f"fps={rate},scale={width}:{height}:flags=area,crop={sw}:{sh}:{left}:{top},format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    ).stdout
    count = len(raw) // (sw * sh)
    return np.frombuffer(raw[: count * sw * sh], dtype=np.uint8).reshape(count, sh, sw)


def app_run(f: Footage) -> tuple[int, int, float]:
    """Phone: the longest stretch in which the chat app is on screen (its title bar
    as in most of the recording), so Control Center at either end is left out.
    Returns the first and last frame and how much of the recording that is."""
    import numpy as np

    rate = 10
    strips = title_strips(f.path, rate).astype(np.int16)
    if len(strips) < 4:
        return 0, f.last, 1.0
    reference = np.median(strips, axis=0)
    # The title's own pixels (the bot's name), as in most of the recording.
    # Control Center blurs the app behind it, so its colours may match the bar's,
    # but the sharp letters are gone.
    mark = np.abs(reference - np.median(reference)) > 40
    if int(mark.sum()) >= 30:
        differ = (np.abs(strips - reference)[:, mark] > 40).mean(axis=1)
        inside = differ <= 0.35
    else:  # no title to read: the bar as a whole
        differ = (np.abs(strips - reference) > 28).reshape(len(strips), -1).mean(axis=1)
        inside = differ <= APP_DIFF
    best, run_start, longest = (0, len(inside) - 1), None, 0
    for index, flag in enumerate([*inside.tolist(), False]):
        if flag and run_start is None:
            run_start = index
        elif not flag and run_start is not None:
            if index - run_start > longest:
                longest, best = index - run_start, (run_start, index - 1)
            run_start = None
    # From the strips' rate to the analysis frames.
    first = f.index(best[0] / rate)
    last = f.index((best[1] + 1) / rate - 1 / RATE)
    return first, last, longest / max(1, len(inside))


def first_change(
    f: Footage, lo: int, hi: int, share: float, rows: tuple[int, int] | None = None
) -> int | None:
    for i in range(max(lo, 3), hi + 1):
        if f.diff(i, i - 3, rows) >= share:
            return i - 3
    return None


def plan_phone(
    f: Footage,
    start: float | None = None,
    end: float | None = None,
    remove: list[tuple[float, float]] | None = None,
    auto_remove: bool = True,
) -> Plan:
    a, b, share = app_run(f)
    events: dict[str, Any] = {
        "app_on_screen": [_r(f.time(a)), _r(f.time(b))],
        "app_share": round(share, 3),
    }
    # Into the run: what slides away at its edges is still moving.
    lo, hi = min(f.last, a + int(0.25 * RATE)), max(0, b - int(0.25 * RATE))
    moved = None
    for i in range(lo + 1, hi + 1):
        if f.diff(i, lo) > LOCAL["phone"]:
            moved = i
            break
    events["first_movement"] = _r(f.time(moved)) if moved is not None else None
    auto_start = max(f.time(lo), (f.time(moved) - LEAD) if moved is not None else f.time(lo))
    # The end: the last time the picture moved on (the answer), settled, and a moment.
    last_move = lo
    for i in range(hi, lo, -1):
        if f.diff(i, hi) > LOCAL["phone"]:
            last_move = i
            break
    done = settled_after(f, last_move)
    events["last_change"], events["settled"] = _r(f.time(last_move)), _r(f.time(done))
    auto_end = min(f.time(hi), f.time(done) + HOLD)
    plan_start = auto_start if start is None else start
    plan_end = auto_end if end is None else end
    if plan_end - plan_start < 2:
        raise Stop(
            f"The phone clip would be {plan_end - plan_start:.1f} s long; check --start and --end."
        )
    found = removals(f, f.index(plan_start), f.index(plan_end)) if auto_remove else []
    events["waits_found"] = [[_r(x), _r(y)] for x, y in found]
    return Plan(
        plan_start,
        plan_end,
        clean_removed(remove if remove is not None else found, plan_start, plan_end),
        1.0,
        events,
    )


def plan_desktop(
    f: Footage,
    marks: dict[str, float],
    start: float | None = None,
    end: float | None = None,
    remove: list[tuple[float, float]] | None = None,
    auto_remove: bool = True,
    speed: float | None = None,
) -> Plan:
    h = f.frames.shape[1]
    upper = (0, int(h * UPPER))
    events: dict[str, Any] = {k: _r(v) for k, v in marks.items()}
    message_at = marks.get("message")
    lo = f.index((message_at - 2.5) if message_at is not None else 0.0)
    bubble = first_change(f, lo, f.last, BIG, upper)
    if bubble is None:
        bubble = first_change(f, lo, f.last, LOCAL["desktop"] * 2)
    events["message_shown"] = _r(f.time(bubble)) if bubble is not None else None
    auto_start = max(0.0, (f.time(bubble) if bubble is not None else f.time(lo)) - LEAD)
    sent = marks.get("answer_sent") or marks.get("answer_done")
    if sent is not None:
        auto_end = min(f.duration - 0.05, sent + HOLD)
    else:
        auto_end = min(f.duration - 0.05, f.time(settled_after(f, f.index(auto_start + 1))) + HOLD)
    plan_start = auto_start if start is None else start
    plan_end = auto_end if end is None else end
    if plan_end - plan_start < 2:
        raise Stop(
            f"The desktop clip would be {plan_end - plan_start:.1f} s long;"
            " check --start and --end."
        )
    found = removals(f, f.index(plan_start), f.index(plan_end)) if auto_remove else []
    events["waits_found"] = [[_r(x), _r(y)] for x, y in found]
    plan = Plan(
        plan_start,
        plan_end,
        clean_removed(remove if remove is not None else found, plan_start, plan_end),
        1.0,
        events,
    )
    if speed is not None:
        plan.speed = speed
    return plan


# --------------------------------------------------------------------------
# Writing a clip
# --------------------------------------------------------------------------


def frames_to_video(take_dir: Path, target: Path) -> dict[str, Any]:
    """The desktop's screencast frames as a 60 fps video: each frame stays on
    screen until the next one was drawn, as on a real screen."""
    take = json.loads((take_dir / "take.json").read_text(encoding="utf-8"))
    frames = take.get("frames") or []
    if len(frames) < 2:
        raise Stop("The desktop take has no footage.")
    stopped = float((take.get("times") or {}).get("stopped") or frames[-1]["ts"] + 1)
    lines = []
    for k, frame in enumerate(frames):
        nxt = frames[k + 1]["ts"] if k + 1 < len(frames) else max(stopped, frame["ts"] + 1 / FPS)
        lines.append(f"file '{take_dir / frame['name']}'")
        lines.append(f"duration {max(1 / FPS, nxt - frame['ts']):.6f}")
    lines.append(f"file '{take_dir / frames[-1]['name']}'")
    listing = take_dir / "frames.txt"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-vf",
            f"fps={FPS},scale=in_range=full:out_range=tv:in_color_matrix=bt601:"
            "out_color_matrix=bt709,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "14",
            "-r",
            str(FPS),
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-color_range",
            "tv",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    if proc.returncode != 0:
        raise Stop("ffmpeg could not write the desktop footage: " + proc.stderr.strip()[-500:])
    ts = [f["ts"] for f in frames]
    gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    busy = [g for g in gaps if g < 0.2]  # where something moved
    return {
        "t0": ts[0],
        "frames": len(frames),
        "seconds": round(stopped - ts[0], 2),
        "moving_fps_median": round(1 / sorted(busy)[len(busy) // 2], 1) if busy else None,
        "longest_gap_s": round(max(gaps), 2) if gaps else 0.0,
    }


def render(source: Path, plan: Plan, target: Path, max_height: int = 0) -> None:
    segments = plan.segments
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for s, e in segments:
        cmd += ["-ss", f"{s:.3f}", "-t", f"{e - s:.3f}", "-i", str(source)]
    size = f"scale=-2:{max_height}:flags=lanczos," if max_height else ""
    # trim: a phone records only when its screen changes, so the last frame of a
    # stretch may last seconds longer than the stretch.
    parts = [
        f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},trim=duration={e - s:.3f},setpts=PTS-STARTPTS,"
        f"{size}crop=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p,settb=AVTB[v{k}]"
        for k, (s, e) in enumerate(segments)
    ]
    video, length = "v0", segments[0][1] - segments[0][0]
    for k in range(1, len(segments)):
        offset = length - DISSOLVE
        parts.append(
            f"[{video}][v{k}]xfade=transition=fade:duration={DISSOLVE}:offset={offset:.3f}[x{k}]"
        )
        video = f"x{k}"
        length = offset + segments[k][1] - segments[k][0]
    tempo = f"setpts=PTS/{plan.speed:.4f}," if plan.speed != 1 else ""
    parts.append(f"[{video}]{tempo}fps={FPS},format=yuv420p[out]")
    cmd += [
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[out]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "14",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-movflags",
        "+faststart",
        str(target),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise Stop("ffmpeg could not write the clip: " + proc.stderr.strip()[-600:])


def measure(clip: Path) -> dict[str, Any]:
    """Frames that differ from the one before, per second; the longest standstill."""
    import numpy as np

    w, h = shown_size(clip)
    mw, mh = (320, 180) if w >= h else (180, max(2, int(round(180 * h / w / 2)) * 2))
    raw = subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"scale={mw}:{mh}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, mh, mw).astype(np.int16)
    if len(frames) < 2:
        return {"frames": int(len(frames))}
    moved = (np.abs(np.diff(frames, axis=0)) > MEASURE_STEP).reshape(len(frames) - 1, -1).sum(
        axis=1
    ) >= MEASURE_PIXELS
    per_second = [int(moved[k : k + FPS].sum()) for k in range(0, len(moved), FPS)]
    longest = run_len = at = begun = 0
    for index, flag in enumerate(moved):
        if flag:
            run_len = 0
            continue
        if run_len == 0:
            begun = index
        run_len += 1
        if run_len > longest:
            longest, at = run_len, begun
    full = per_second[:-1] if len(moved) % FPS else per_second
    info = probe(clip)
    return {
        "size": [w, h],
        "seconds": round(info["duration"], 2),
        "frames": int(len(frames)),
        "changed_share": round(float(moved.mean()), 3),
        "changed_per_second": per_second,
        "lowest_full_second": min(full) if full else None,
        "longest_standstill_s": round(longest / FPS, 2),
        "longest_standstill_at_s": round(at / FPS, 2),
        "megabytes": round(clip.stat().st_size / 1e6, 2),
    }


def stills(clip: Path, folder: Path, every: float) -> list[tuple[float, Path]]:
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(clip),
            "-vf",
            f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{every - 0.001:.3f})'",
            "-fps_mode",
            "vfr",
            str(folder / "s%04d.png"),
        ]
    )
    return [(round(k * every, 2), path) for k, path in enumerate(sorted(folder.glob("s*.png")))]


def contact_sheet(clip: Path, sheet: Path, workdir: Path) -> int:
    from PIL import Image, ImageDraw

    shots = stills(clip, workdir / "sheet", 1.0)
    if not shots:
        return 0
    with Image.open(shots[0][1]) as first:
        portrait = first.height > first.width
        ratio = first.height / first.width
    columns, tile_w = (6, 240) if portrait else (4, 480)
    tile_h = int(round(tile_w * ratio))
    label = 22
    rows = math.ceil(len(shots) / columns)
    canvas = Image.new(
        "RGB", (columns * (tile_w + 8) + 8, rows * (tile_h + label + 8) + 8), (32, 32, 32)
    )
    draw = ImageDraw.Draw(canvas)
    for n, (second, path) in enumerate(shots):
        x = 8 + (n % columns) * (tile_w + 8)
        y = 8 + (n // columns) * (tile_h + label + 8)
        with Image.open(path) as image:
            canvas.paste(image.convert("RGB").resize((tile_w, tile_h), Image.LANCZOS), (x, y))
        draw.text((x + 2, y + tile_h + 4), f"{second:.0f} s", fill=(220, 220, 220))
    canvas.save(sheet)
    return len(shots)


_VISION: dict[str, Any] = {}


def read_text(png: Path) -> str:
    """The text macOS reads in a picture (on this Mac; nothing is sent anywhere)."""
    import objc
    import Quartz
    from Foundation import NSURL

    if not _VISION:
        objc.loadBundle("Vision", {}, bundle_path="/System/Library/Frameworks/Vision.framework")
        _VISION["handler"] = objc.lookUpClass("VNImageRequestHandler")
        _VISION["request"] = objc.lookUpClass("VNRecognizeTextRequest")
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(png)), None)
    if source is None:
        return ""
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    request = _VISION["request"].alloc().init()
    request.setRecognitionLevel_(0)
    request.setUsesLanguageCorrection_(False)
    handler = _VISION["handler"].alloc().initWithCGImage_options_(image, {})
    done = handler.performRequests_error_([request], None)
    if not (done[0] if isinstance(done, tuple) else done):
        return ""
    return "\n".join(str(obs.topCandidates_(1)[0].string()) for obs in (request.results() or []))


def sensitive_terms(
    owner_names: dict[str, str],
    extra: list[tuple[str, str]] | None = None,
    profile: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Words that must not be readable in a clip, with what they are (never printed)."""
    terms: list[tuple[str, str]] = []

    def add(kind: str, value: str | None, split: bool = True) -> None:
        value = (value or "").strip()
        if len(value) >= 3 and value.lower() not in NAME_STOP:
            terms.append((kind, value.lower()))
        if split:
            for token in re.split(r"[\s._@'-]+", value):
                if len(token) >= 3 and token.lower() not in NAME_STOP:
                    terms.append((kind, token.lower()))

    add("account name", getpass.getuser())
    add("account name", run(["id", "-F"]).stdout)
    for key in ("ComputerName", "LocalHostName"):
        add("computer name", run(["scutil", "--get", key]).stdout)
    add("computer name", socket.gethostname().split(".")[0])
    for key in ("first_name", "last_name", "username"):
        add("Telegram name", owner_names.get(key))
    user = (profile or {}).get("user") or {}
    add("profile name", user.get("name"))
    add("profile name", user.get("display_name"))
    for kind, value in extra or []:
        add(kind, value, split=False)
    unique, seen = [], set()
    for kind, term in terms:
        if term not in seen:
            seen.add(term)
            unique.append((kind, term))
    return unique


def privacy_check(
    clip: Path, terms: list[tuple[str, str]], workdir: Path, every: float = 0.5
) -> dict[str, Any]:
    if not ocr_available():
        return {"checked": False, "why": "PyObjC is missing: look at the sheet yourself."}
    shots = stills(clip, workdir / "ocr", every)
    found: dict[tuple[float, str], dict[str, Any]] = {}
    lines = 0
    for second, png in shots:
        text = read_text(png)
        lines += len(text.splitlines())
        low = text.lower()
        for kind, term in terms:
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", low):
                found.setdefault((second, kind), {"second": second, "kind": kind})
        for address in EMAIL_RE.findall(text):
            if not ALLOWED_EMAIL.search(address):
                found.setdefault(
                    (second, "e-mail address"), {"second": second, "kind": "e-mail address"}
                )
    return {
        "checked": True,
        "stills": len(shots),
        "every_s": every,
        "lines_read": lines,
        "terms": len(terms),
        "findings": sorted(found.values(), key=lambda x: (x["second"], x["kind"])),
    }


def cut_clip(
    kind: str,
    raw: Path,
    master: Path,
    sheet: Path,
    terms: list[tuple[str, str]],
    marks: dict[str, float] | None = None,
    args: argparse.Namespace | None = None,
    lock_enabled: bool = True,
) -> dict[str, Any]:
    """Plan, render, measure and read one clip; the report of it."""
    footage = read_footage(raw, kind)
    start = getattr(args, "start", None)
    end = getattr(args, "end", None)
    remove = [span(text) for text in getattr(args, "remove", [])] or None
    auto = not getattr(args, "no_auto_remove", False)
    if kind == "phone":
        plan = plan_phone(footage, start, end, remove, auto)
    else:
        plan = plan_desktop(
            footage, marks or {}, start, end, remove, auto, getattr(args, "speed", None)
        )
    say(
        f"  {kind}: keeps {', '.join(f'{s:.2f}-{e:.2f}' for s, e in plan.segments)} s"
        " of the raw recording, "
        f"cuts {len(plan.removed)} wait(s), {plan.length:.1f} s long"
    )
    lock = FilmLock(f"telegram_take.py (render {kind})", enabled=lock_enabled)
    lock.take()
    try:
        render(
            raw, plan, master, max_height=2560 if kind == "phone" and footage.size[1] > 2560 else 0
        )
    finally:
        lock.release()
    with tempfile.TemporaryDirectory(prefix="tgtake-") as tmp:
        numbers = measure(master)
        count = contact_sheet(master, sheet, Path(tmp))
        privacy = privacy_check(master, terms, Path(tmp))
    info = probe(raw)
    video = info["video"] or {}
    return {
        "raw": str(raw),
        "raw_seconds": _r(info["duration"], 2),
        "raw_size": list(footage.size),
        "raw_codec": video.get("codec_name"),
        "raw_frames": frame_rates(raw),
        "raw_audio": bool(info["audio"]),
        "events": plan.events,
        "cut": {
            "start": _r(plan.start),
            "end": _r(plan.end),
            "kept": [[_r(s), _r(e)] for s, e in plan.segments],
            "removed": [[_r(a), _r(b)] for a, b in plan.removed],
            "dissolve_s": DISSOLVE,
            "speed": plan.speed,
            "length_s": round(plan.length, 2),
        },
        "master": str(master),
        "sheet": str(sheet),
        "sheet_stills": count,
        "measure": numbers,
        "privacy": privacy,
    }


def span(text: str) -> tuple[float, float]:
    a, _, b = text.partition("-")
    try:
        return float(a), float(b)
    except ValueError as exc:
        raise Stop(f"--remove wants FROM-TO in seconds, not {text!r}.") from exc


# --------------------------------------------------------------------------
# A made-up phone recording, for the dry run
# --------------------------------------------------------------------------


def made_up_phone_video(target: Path, answer: str, workdir: Path) -> dict[str, Any]:
    """A portrait screen recording of a chat with a bot, the way a phone makes one:
    it starts on Control Center, a message is typed and sent, the answer comes
    after a wait, and Control Center comes down again to stop it. HEVC, frames
    only when the picture changes (a variable frame rate), with a silent sound
    track. TEST_NAME stands in Control Center only: the cut must remove it."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 828, 1792
    s = W / 414  # points to pixels
    font = "/System/Library/Fonts/Helvetica.ttc"

    def f(size: float) -> Any:
        try:
            return ImageFont.truetype(font, int(size * s))
        except OSError:
            return ImageFont.load_default()

    bg, bar, me_c, it_c, text_c, dim = (
        (24, 28, 36),
        (33, 38, 48),
        (43, 110, 200),
        (45, 50, 62),
        (236, 238, 242),
        (140, 146, 156),
    )

    def wrap(text: str, width: float, size: float) -> list[str]:
        words, lines, line = text.split(), [], ""
        probe_draw = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        for word in words:
            trial = (line + " " + word).strip()
            if probe_draw.textlength(trial, font=f(size)) > width and line:
                lines.append(line)
                line = word
            else:
                line = trial
        return [*lines, line] if line else lines

    def bubble(d: Any, y: float, text: str, mine: bool) -> float:
        lines = wrap(text, 250 * s, 16)
        lh = 21 * s
        bw = max(d.textlength(line, font=f(16)) for line in lines) + 26 * s
        bh = lh * len(lines) + 16 * s
        x = W - bw - 10 * s if mine else 10 * s
        d.rounded_rectangle([x, y - bh, x + bw, y], radius=16 * s, fill=me_c if mine else it_c)
        for n, line in enumerate(lines):
            d.text((x + 13 * s, y - bh + 8 * s + n * lh), line, font=f(16), fill=text_c)
        return y - bh - 8 * s

    def chat(
        clock: str,
        typed: str,
        keyboard: float,
        caret: bool,
        popup: tuple[float, float] | None,
        sent: bool,
        answer_in: float,
    ) -> Image.Image:
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img)
        for gx in range(0, W, int(46 * s)):  # a faint pattern, as chat wallpapers have
            for gy in range(int(110 * s), H, int(46 * s)):
                d.ellipse([gx + 20, gy + 20, gx + 24, gy + 24], fill=(30, 34, 43))
        d.text((24 * s, 14 * s), clock, font=f(16), fill=text_c)
        d.rounded_rectangle(
            [20 * s, 12 * s, 76 * s, 34 * s], radius=11 * s, outline=(230, 60, 60), width=3
        )
        d.rectangle([W - 60 * s, 18 * s, W - 30 * s, 30 * s], outline=text_c, width=2)
        d.rectangle([0, 44 * s, W, 100 * s], fill=bar)
        d.text((12 * s, 60 * s), "< Chats", font=f(17), fill=(90, 160, 240))
        title = ASSISTANT
        d.text(((W - d.textlength(title, font=f(17))) / 2, 52 * s), title, font=f(17), fill=text_c)
        d.text(((W - d.textlength("bot", font=f(13))) / 2, 74 * s), "bot", font=f(13), fill=dim)
        d.ellipse([W - 52 * s, 52 * s, W - 14 * s, 90 * s], fill=(120, 90, 200))
        d.text((W - 39 * s, 60 * s), "N", font=f(18), fill=text_c)
        kb_h = 290 * s * keyboard
        input_y = H - 34 * s - kb_h - 52 * s
        y = input_y - 14 * s
        if answer_in > 0:
            y = bubble(d, y + (1 - answer_in) * 30 * s, answer, False)
        if sent:
            y = bubble(d, y, SENTENCE, True)
        y = bubble(
            d,
            y,
            "Telegram is connected. Send a message here and I will forward it directly to Dodaios.",
            False,
        )
        bubble(d, y, "/start", True)
        d.rectangle([0, input_y, W, H], fill=bar)
        d.rounded_rectangle(
            [12 * s, input_y + 9 * s, W - 56 * s, input_y + 43 * s], radius=17 * s, fill=bg
        )
        shown = typed[-30:] if typed else ""
        if typed:
            d.text((24 * s, input_y + 17 * s), shown, font=f(16), fill=text_c)
        else:
            d.text((24 * s, input_y + 17 * s), "Message", font=f(16), fill=dim)
        if caret and keyboard > 0.99:
            cx = 24 * s + d.textlength(shown, font=f(16)) + 2
            d.rectangle([cx, input_y + 15 * s, cx + 2 * s, input_y + 37 * s], fill=(90, 160, 240))
        if typed:
            d.ellipse([W - 48 * s, input_y + 8 * s, W - 12 * s, input_y + 44 * s], fill=me_c)
        if keyboard > 0:
            top = H - kb_h - 34 * s
            d.rectangle([0, top, W, H], fill=(52, 56, 66))
            for row, count in enumerate((10, 9, 7)):
                for k in range(count):
                    kx = (W - count * 39 * s) / 2 + k * 39 * s
                    ky = top + 12 * s + row * 54 * s
                    d.rounded_rectangle(
                        [kx + 3 * s, ky, kx + 36 * s, ky + 44 * s], radius=5 * s, fill=(94, 99, 110)
                    )
            d.rounded_rectangle(
                [100 * s, top + 176 * s, W - 100 * s, top + 220 * s],
                radius=5 * s,
                fill=(94, 99, 110),
            )
            if popup is not None:
                px, py = popup
                d.rounded_rectangle(
                    [px - 26 * s, top + py - 70 * s, px + 26 * s, top + py + 10 * s],
                    radius=10 * s,
                    fill=(150, 155, 165),
                )
        return img

    def control_center(cover: float, base: Image.Image) -> Image.Image:
        img = base.copy()
        layer = Image.new("RGB", (W, H), (18, 18, 22))
        d = ImageDraw.Draw(layer)
        for row in range(4):
            for col in range(4):
                x0, y0 = 30 * s + col * 92 * s, 110 * s + row * 92 * s
                d.rounded_rectangle(
                    [x0, y0, x0 + 76 * s, y0 + 76 * s], radius=18 * s, fill=(58, 58, 64)
                )
        d.ellipse([214 * s, 386 * s, 290 * s, 462 * s], fill=(220, 50, 50))
        d.text((40 * s, 520 * s), TEST_NAME, font=f(22), fill=text_c)
        d.text((40 * s, 556 * s), "Now Playing", font=f(15), fill=dim)
        shift = int((1 - cover) * H)
        img.paste(layer.crop((0, shift, W, H)), (0, 0))
        return img

    shots: list[tuple[float, Image.Image]] = []
    t = 0.0

    def add(image: Image.Image, seconds: float) -> None:
        nonlocal t
        shots.append((seconds, image))
        t += seconds

    clock = "17:42"
    calm = chat(clock, "", 0, False, None, False, 0)
    add(control_center(1.0, calm), 2.4)
    for k in range(1, 25):
        add(control_center(1 - k / 24, calm), 1 / 60)
    add(calm, 1.1)
    for k in range(1, 19):
        add(chat(clock, "", k / 18, False, None, False, 0), 1 / 60)
    add(chat(clock, "", 1, True, None, False, 0), 0.6)
    typed = ""
    for n, ch in enumerate(SENTENCE):
        key_x = (60 + (n * 37) % 300) * (W / 414)
        key_y = (12 + (n % 3) * 54) * (W / 414)
        add(chat(clock, typed, 1, True, (key_x, key_y), False, 0), 0.08)
        typed += ch
        add(chat(clock, typed, 1, n % 6 != 5, None, False, 0), 0.12 if ch != " " else 0.2)
    add(chat(clock, typed, 1, True, None, False, 0), 0.5)
    add(chat(clock, "", 1, True, None, True, 0), 0.5)
    for k in range(14):  # the wait for the answer: only the caret blinks
        if k == 7:
            clock = "17:43"
        add(chat(clock, "", 1, k % 2 == 0, None, True, 0), 0.5)
    for k in range(1, 13):
        add(chat(clock, "", 1, True, None, True, k / 12), 1 / 60)
    done = chat(clock, "", 1, True, None, True, 1)
    add(done, 3.2)
    for k in range(1, 25):
        add(control_center(k / 24, done), 1 / 60)
    add(control_center(1.0, done), 1.6)

    folder = workdir / "made-up-phone"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    lines = []
    for n, (seconds, image) in enumerate(shots):
        name = folder / f"{n:05d}.png"
        image.save(name, compress_level=1)
        lines += [f"file '{name}'", f"duration {seconds:.6f}"]
    lines.append(f"file '{folder / f'{len(shots) - 1:05d}.png'}'")
    (folder / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(folder / "list.txt"),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-shortest",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx265",
            "-tag:v",
            "hvc1",
            "-pix_fmt",
            "yuv420p",
            "-x265-params",
            "log-level=error",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-c:a",
            "aac",
            "-video_track_timescale",
            "600",
            str(target),
        ]
    )
    shutil.rmtree(folder, ignore_errors=True)
    if proc.returncode != 0:
        raise Stop("ffmpeg could not make the made-up phone video: " + proc.stderr.strip()[-400:])
    return {"seconds": round(t, 2), "pictures": len(shots), "size": [W, H]}


# --------------------------------------------------------------------------
# The take
# --------------------------------------------------------------------------


def new_events(
    instance: Instance, session_id: str, after: int, tail: int = 80
) -> list[dict[str, Any]]:
    return [e for e in instance.events(session_id, tail) if e["seq"] > after]


def turn_text(events: list[dict[str, Any]], turn_id: str) -> str:
    parts = [
        str((e["payload"] or {}).get("text") or "")
        for e in events
        if e["kind"] == "assistant_text" and (e["payload"] or {}).get("turn_id") == turn_id
    ]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def downloads_names(folder: Path) -> set[str]:
    """The names in the folder the recording will land in (only names are read)."""
    try:
        return {entry.name for entry in os.scandir(folder)}
    except FileNotFoundError:
        raise Stop(
            f"{folder} does not exist; name the folder AirDrop saves to with --downloads."
        ) from None
    except PermissionError:
        raise Stop(
            f"This Terminal may not read {folder}, where the AirDropped recording lands. Allow it"
            " in System Settings > Privacy & Security > Files and Folders (Terminal: Downloads"
            " Folder), then run this again."
        ) from None


def video_candidates(folder: Path, known: set[str], since: float) -> list[Path]:
    out = []
    with contextlib.suppress(OSError):
        for entry in os.scandir(folder):
            if entry.name in known or entry.name.startswith(".") or not entry.is_file():
                continue
            if Path(entry.name).suffix.lower() not in VIDEO_SUFFIXES:
                continue
            st = entry.stat()
            if getattr(st, "st_birthtime", st.st_mtime) < since - 2:
                continue
            out.append(Path(entry.path))
    return sorted(out, key=lambda p: p.stat().st_mtime)


def wait_for_video(folder: Path, known: set[str], since: float, timeout: float) -> Path | None:
    """The first new video in ``folder`` once it is complete (its size stays the
    same and ffprobe reads it)."""
    end = time.time() + timeout
    sizes: dict[Path, tuple[int, float]] = {}
    told = False
    while time.time() < end:
        for path in video_candidates(folder, known, since):
            size = path.stat().st_size
            seen = sizes.get(path)
            if seen is None or seen[0] != size:
                sizes[path] = (size, time.time())
                if not told:
                    say(f"  {path.name} is arriving ...")
                    told = True
                continue
            if time.time() - seen[1] >= 3 and size > 0 and probe(path)["duration"] > 0:
                return path
        time.sleep(1.5)
    return None


def keep_newest(folder: Path, pattern: str, keep: int) -> None:
    for old in sorted(folder.glob(pattern))[:-keep]:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
        else:
            old.unlink(missing_ok=True)


def warm_up(paths: Paths, instance: Instance, modules: Path) -> dict[str, Any]:
    say()
    say("Warm-up of the demo instance (not filmed; the model works for real, about 5 minutes)")
    instance.start(keep=False, label="warmup")
    item("instance", f"{paths.origin}/  (home {paths.home})")
    run_record_cjs(paths, modules, "setup,warmup", paths.work / "warmup")
    lead = instance.lead()
    if MODEL_ID not in str(lead.get("model") or ""):
        instance.send(
            "PATCH", f"/api/agent-chat/sessions/{lead['session_id']}", {"model": MODEL_ID}
        )
    before = max([e["seq"] for e in instance.events(lead["session_id"], 5)] or [0])
    say(f'    one more line to {ASSISTANT}: "{WARM_LINE}"')
    sent = instance.send(
        "POST", f"/api/agent-chat/sessions/{lead['session_id']}/messages", {"text": WARM_LINE}
    )
    if not sent:
        raise Stop("The instance did not take the warm-up line.")
    instance.wait_settled(lead["session_id"], before, timeout=600)
    lead = instance.lead()
    events = instance.events(lead["session_id"], 400)
    threads = (instance.get("/api/agent-chat/sessions?surface=agent") or {}).get("sessions") or []
    info = {
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "code": code_commit(paths.code),
        "lead_session": lead["session_id"],
        "lead_model": lead.get("model"),
        "lead_turns": sum(1 for e in events if e["kind"] == "turn_finished"),
        "threads": len(threads),
    }
    instance.stop()
    save_warm(paths, info)
    item(
        "warm-up",
        f"done: {info['lead_turns']} turns of {ASSISTANT} ({info['lead_model']}), "
        f"{info['threads']} coding threads",
    )
    return info


def run_take(args: argparse.Namespace) -> int:
    dry, fake_mode = bool(args.dry_run), bool(args.fake_telegram)
    if fake_mode and not dry:
        raise Stop("--fake-telegram goes with --dry-run.")
    paths = make_paths(args)
    out = paths.out
    if dry:
        out = paths.out / "telegram-dry-run"
        paths.out = out
    say("Telegram take for the README" + (" (dry run, no person needed)" if dry else ""))
    say()
    say("1. Checks")
    need_tools()
    check_paths(paths)
    if not chrome_installed():
        raise Stop("Google Chrome is not installed; the desktop is filmed with it.")
    modules = ensure_playwright()
    load, free = machine_state(out)
    item("this Mac", f"load {load:.1f}, {free / 1024**3:.1f} GB free")
    if free < MIN_FREE_BYTES:
        raise Stop(
            "Less than 2 GB free on the disk: the desktop footage alone needs up to a gigabyte."
        )
    if load > 6:
        say("  ! The Mac is busy: frames may come unevenly. Better when the load is under 5.")
    item("OCR (privacy check)", "macOS text recognition" if ocr_available() else "missing (PyObjC)")
    if not dry:
        downloads_names(paths.downloads)  # macOS asks now, not after the take
        item("AirDrop arrives in", str(paths.downloads))
    instance = Instance(paths, args.python)
    fake: FakeBotApi | None = None
    token, me, kept = "", dict(FAKE_BOT), False
    if not dry:
        say()
        say("2. The demo bot")
        token, me, kept = obtain_token(paths, args.new_token)
    bot_name = str(me.get("username") or "")
    link = f"https://t.me/{bot_name}"
    if not dry:
        item("link", link)
    commit = ensure_code(paths, args.fresh, args.bundle)
    item("code", f"{commit[:10]} (a copy in {paths.code})")
    say()
    say("3. The demo instance")
    info = warm_info(paths)
    if info is None or args.fresh:
        info = warm_up(paths, instance, modules)
    else:
        item(
            "warm-up",
            f"kept from {info.get('at')} ({info.get('lead_turns')} turns,"
            f" model {info.get('lead_model')})",
        )
    used = paths.state / ".telegram-take-used"
    if used.exists() or not paths.config.exists():
        restore_warm(paths)
        item("state", "back to the warm-up copy")
    used.write_text(dt.datetime.now().isoformat(), encoding="utf-8")
    owner: dict[str, Any] = {}
    if not dry and paths.owner_file.exists():
        with contextlib.suppress(OSError, ValueError):
            owner = json.loads(paths.owner_file.read_text(encoding="utf-8"))
    if owner.get("bot") == bot_name and owner.get("user_id"):
        set_owner(paths.config, int(owner["user_id"]))
        item("Telegram owner", "paired in an earlier take (kept)")
    else:
        owner = {}

    telegram: Telegram | None = None
    if fake_mode:
        fake = FakeBotApi().start()
        shim = paths.work / "fake-telegram"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "sitecustomize.py").write_text(SHIM, encoding="utf-8")
        telegram = Telegram(token=FAKE_TOKEN, fake_url=fake.url, shim=shim)
        _SECRETS.append(FAKE_TOKEN)
        item("Telegram", f"the local stand-in Bot API at {fake.url}")
    elif not dry:
        # Only a bot an earlier take of this script used: what was sent to it while
        # no instance ran (a take given up) must not be answered at the start.
        drained = 0
        try:
            drained = BotApi(token).drain() if kept else 0
        except TelegramError as exc:
            if exc.code == 409:
                raise Stop(
                    "Another program reads this bot right now (Telegram says: " + str(exc) + ")."
                    " Use a bot made only for the demo, or stop the other program."
                ) from None
            raise Stop(f"Telegram did not answer: {exc}") from None
        if drained:
            item("old messages", f"{drained} sent while no instance ran: marked read, not answered")
        telegram = Telegram(token=token)
    if not dry:
        say()
        beep()
        if sys.stdin and sys.stdin.isatty():
            say("  Ready for step 2. Have your phone in your hand, then press Return here.")
            while not wait_key(3600):
                pass
        else:
            say("  Ready for step 2 (no terminal to press Return in: going on).")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    take_dir = paths.work / f"desktop-{stamp}"
    scrub_file = paths.work / f"scrub-{stamp}.txt"
    write_private(scrub_file, "")
    film: Film | None = None
    lock = FilmLock("telegram_take.py (the desktop of the Telegram take)", enabled=not args.no_lock)
    timeline: dict[str, float] = {}
    report: dict[str, Any] = {"dry_run": dry, "fake_telegram": fake_mode, "sentence": args.sentence}
    owner_names: dict[str, str] = {}
    answer = ""
    try:
        instance.start(keep=True, telegram=telegram, label="take")
        item("instance", f"{paths.origin}/ (Telegram {'on' if telegram else 'off'})")
        profile = instance.get("/api/profile")
        if telegram:
            row = instance.wait_channel()
            item("Telegram channel", f"connected as {row.get('handle')}")
        film = Film(paths, modules, take_dir, scrub_file)
        lead = instance.lead()
        sid = lead["session_id"]
        baseline = max([e["seq"] for e in instance.events(sid, 5)] or [0])
        start_at = time.time()
        timeline["take_start"] = start_at
        downloads_known = set() if dry else downloads_names(paths.downloads)
        window = pairing_window_s(paths)
        say()
        if dry:
            say("4. The take (a stand-in sends the message)")
        else:
            say("4. Step 2, on your phone (Do Not Disturb on, so no notice shows):")
            if owner:
                say(
                    f"     a. Open the chat with the bot ({link});"
                    " it knows you already, no Start needed."
                )
                say("        (For a clean picture, clear the chat's history first.)")
            else:
                say(f"     a. Open {link} in Telegram and tap Start.")
            say(
                "     b. Start the screen recording (Control Center, the record button),"
                " close Control Center."
            )
            say("     c. Type and send:")
            say(f"          \033[1m{args.sentence}\033[0m")
            say(
                f"     d. Wait for {ASSISTANT}'s answer, look at it for two seconds,"
                " stop the recording."
            )
            say("     e. Photos: the recording, Share, AirDrop, this Mac.")
            say("  This window follows along; nothing to do here.")
        armed = False

        def arm() -> None:
            nonlocal armed
            if not armed:
                lock.take()
                film.command("arm", "armed")
                armed = True

        def learn_owner(user_id: int) -> None:
            nonlocal owner, owner_names
            if owner_names:
                return
            try:
                api = BotApi(FAKE_TOKEN, fake.url.rstrip("/")) if fake else BotApi(token)
                chat = api.call("getChat", chat_id=user_id) or {}
            except TelegramError as exc:
                say(
                    f"  (Telegram did not say the sender's name: {exc};"
                    " the privacy reading still runs)"
                )
                chat = {}
            owner_names = {
                k: str(chat.get(k) or "") for k in ("first_name", "last_name", "username")
            }
            pairs = []
            first, last, user = (
                owner_names["first_name"],
                owner_names["last_name"],
                owner_names["username"],
            )
            if first and last:
                pairs.append(f"{first} {last}={PERSONA[0]} {PERSONA[1]}")
            if first:
                pairs.append(f"{first}={PERSONA[0]}")
            if last:
                pairs.append(f"{last}={PERSONA[1]}")
            if user:
                pairs.append(f"{user}={PERSONA[2]}")
            write_private(scrub_file, "\n".join(pairs) + "\n")
            film.command(f"scrub {scrub_file}", "scrubbed")
            if not dry:
                owner = {"bot": bot_name, "user_id": user_id}
                write_private(paths.owner_file, json.dumps(owner) + "\n")

        message: dict[str, Any] | None = None
        if dry:
            arm()
            time.sleep(1.5)
            if fake:
                fake.send_from(FAKE_OWNER, "/start")
                end = time.time() + 30
                while time.time() < end and not (
                    instance.owner_ids() and fake.sent_to(FAKE_OWNER["id"])
                ):
                    time.sleep(0.3)
                if FAKE_OWNER["id"] not in instance.owner_ids():
                    raise Stop("The stand-in sender was not paired by /start.")
                timeline["paired"] = time.time()
                item(
                    "paired",
                    "the stand-in sender, by /start: "
                    + (fake.sent_to(FAKE_OWNER["id"]) or [{}])[0].get("text", "")[:60],
                )
                learn_owner(FAKE_OWNER["id"])
                time.sleep(2.0)
                fake.send_from(FAKE_OWNER, args.sentence)
            else:
                posted = instance.send(
                    "POST", f"/api/agent-chat/sessions/{sid}/messages", {"text": args.sentence}
                )
                if not posted:
                    raise Stop("The instance did not take the stand-in message.")
        reopened = 0
        deadline = time.time() + 45 * 60
        told_paired = bool(owner) or dry  # a dry run has no person to tell
        conflict_checked = 0.0
        while message is None:
            if time.time() > deadline:
                raise Stop("No message arrived within 45 minutes. Run this again to retry.")
            ids = instance.owner_ids()
            if ids and not told_paired:
                timeline.setdefault("paired", time.time())
                learn_owner(ids[0])
                arm()
                say(
                    "  Telegram paired with your account. Start the screen recording now,"
                    " then send the sentence."
                )
                told_paired = True
            elif told_paired and not armed:
                arm()
            for event in new_events(instance, sid, baseline):
                if event["kind"] == "user_message":
                    message = event
                    break
            if telegram and not fake and time.time() - conflict_checked > 5:
                conflict_checked = time.time()
                if "Conflict: terminated by other getUpdates" in instance.log_text():
                    raise Stop(
                        "Another program reads this bot too (Telegram: Conflict), so messages do"
                        " not arrive here. Use a bot made only for the demo, or stop the other"
                        " program."
                    )
            if (
                message is None
                and not ids
                and telegram
                and not fake
                and time.time() - instance.channel_since > window - 45
            ):
                # The channel accepts a first sender only shortly after it starts.
                reopened += 1
                say(
                    "  Nobody wrote to the bot yet; opening the pairing window again"
                    " (a short restart)."
                )
                instance.stop()
                instance.start(keep=True, telegram=telegram, label=f"take-reopen{reopened}")
                instance.wait_channel()
                film.command("reload", "ready", 120)
                say(f"  Ready again: tap Start in {link} (or send /start).")
            time.sleep(0.25)
        arrived = message["ts_ms"] / 1000.0
        timeline["message"] = arrived
        arm()
        film.command(f"record {arrived:.3f}", "recording")
        turn_id = str((message["payload"] or {}).get("turn_id") or "")
        # What the person wrote: a phone chat's message is stored with a line for the
        # model after it, which the app does not draw.
        typed = str(
            (message["payload"] or {}).get("typed") or (message["payload"] or {}).get("text") or ""
        )
        report["message_typed"] = typed
        item("message arrived", '"' + typed[:100] + '"')
        if instance.owner_ids() and not owner_names:
            learn_owner(instance.owner_ids()[0])
        finished = None
        end = time.time() + 15 * 60
        while finished is None:
            if time.time() > end:
                raise Stop(f"{ASSISTANT} was still working after 15 minutes.")
            events = new_events(instance, sid, baseline)
            if not turn_id:
                # The message's event carries no turn id; the turn it starts
                # (now, or after a running one) names it first.
                turn_id = next(
                    (
                        str((e["payload"] or {}).get("turn_id") or "")
                        for e in events
                        if e["kind"] == "turn_started" and e["seq"] > message["seq"]
                    ),
                    "",
                )
            for event in events:
                payload = event["payload"] or {}
                if (
                    event["kind"] == "turn_finished"
                    and turn_id
                    and payload.get("turn_id") == turn_id
                ):
                    finished = event
            time.sleep(0.3)
        timeline["answer_done"] = finished["ts_ms"] / 1000.0
        log_mark = instance.log_size()
        status = str((finished["payload"] or {}).get("status") or "")
        answer = turn_text(new_events(instance, sid, baseline, 400), turn_id)
        item(
            "answer",
            (f"({status}) " if status not in ("", "done", "completed") else "")
            + answer[:160].replace("\n", " "),
        )
        if not answer:
            say("  ! The turn ended without words: the take shows no answer. Run it again.")
        # The bridge sends the answer once the turn is over.
        sent_at = None
        end = time.time() + (30 if fake else 4)
        while sent_at is None and time.time() < end:
            if fake:
                replies = fake.sent_to(FAKE_OWNER["id"], after=timeline["answer_done"] - 0.5)
                if replies:
                    sent_at = replies[0]["at"]
                    report["telegram_reply"] = replies[0]["text"]
            elif telegram:
                fresh = instance.log_text(log_mark)
                if re.search(r"sendMessage|send_message failed", fresh):
                    sent_at = time.time()
                    if "send_message failed" in fresh:
                        say(
                            "  ! The instance says it could not send the answer to Telegram:"
                            " see its log."
                        )
            else:
                sent_at = timeline["answer_done"]
            time.sleep(0.2)
        if sent_at is None:
            # The instance logs no line when the bridge sends; it sends right
            # after the turn (one request to Telegram).
            sent_at = timeline["answer_done"] + 1.0
            report["answer_sent_estimated"] = True
        timeline["answer_sent"] = sent_at
        time.sleep(max(0.0, sent_at + HOLD + 0.6 - time.time()))
        film.command("mark end", "marked")
        film.stop()
        film = None
        lock.release()
        timeline["filmed_until"] = time.time()
    except KeyboardInterrupt:
        say("\n  Stopped. Run the same command again to retry.")
        return 1
    finally:
        if film is not None:
            film.stop()
        lock.release()
        if not args.keep_running:
            instance.stop()
        if fake is not None:
            report["fake_calls"] = sorted({name for _, name in fake.calls})
            fake.stop()
        scrub_file.unlink(missing_ok=True)
    say(
        "  The desktop is filmed; the demo instance "
        + (
            "still runs (--keep-running)."
            if args.keep_running
            else "is stopped (its state is kept)."
        )
    )

    # ---- the desktop clip -------------------------------------------------
    say()
    say("5. The clips")
    paths.raw.mkdir(parents=True, exist_ok=True)
    desktop_raw = paths.raw / f"desktop-raw-{stamp}.mp4"
    footage = frames_to_video(take_dir, desktop_raw)
    shutil.copy(take_dir / "take.json", paths.raw / f"desktop-raw-{stamp}.json")
    t0 = footage["t0"]
    marks = {
        k: v - t0
        for k, v in timeline.items()
        if k in ("message", "answer_done", "answer_sent", "paired")
    }
    (paths.raw / f"desktop-raw-{stamp}.marks.json").write_text(
        json.dumps(marks, indent=2) + "\n", encoding="utf-8"
    )
    shutil.rmtree(take_dir, ignore_errors=True)
    terms = sensitive_terms(owner_names, profile=profile)
    desktop = cut_clip(
        "desktop",
        desktop_raw,
        out / "telegram-desktop-master.mp4",
        out / "telegram-desktop-sheet.png",
        terms,
        marks,
        lock_enabled=not args.no_lock,
    )
    desktop["footage"] = footage
    report["desktop"] = desktop

    # ---- the phone clip ---------------------------------------------------
    phone_src: Path | None = None
    if dry:
        stand_in = paths.work / "stand-in-downloads"
        stand_in.mkdir(parents=True, exist_ok=True)
        made = paths.work / f"made-up-{stamp}.mov"
        report["made_up_phone"] = made_up_phone_video(
            made, (report.get("telegram_reply") or answer or "All tests pass.")[:300], paths.work
        )
        known = {p.name for p in stand_in.iterdir()}
        since = time.time()

        def deliver() -> None:
            time.sleep(2.0)  # it arrives a moment later, as an AirDrop does
            shutil.copy(made, stand_in / f"ScreenRecording_{stamp}.MOV")

        threading.Thread(target=deliver, daemon=True).start()
        phone_src = wait_for_video(stand_in, known, since, 60)
    else:
        say(
            f"  Waiting for the screen recording in {paths.downloads}"
            " (AirDrop it from Photos to this Mac)."
        )
        say("  Ctrl-C stops waiting; cut it later with: telegram_take.py cut phone <file>")
        try:
            phone_src = wait_for_video(
                paths.downloads, downloads_known, timeline["take_start"], 45 * 60
            )
        except KeyboardInterrupt:
            phone_src = None
    if phone_src is not None:
        phone_raw = paths.raw / f"phone-raw-{stamp}{phone_src.suffix.lower()}"
        shutil.copy2(phone_src, phone_raw)
        item("phone recording", f"{phone_src.name} -> {phone_raw}")
        phone_terms = terms + ([("test name", TEST_NAME.lower())] if dry else [])
        phone = cut_clip(
            "phone",
            phone_raw,
            out / "telegram-phone-master.mp4",
            out / "telegram-phone-sheet.png",
            phone_terms,
            lock_enabled=not args.no_lock,
        )
        if dry:
            phone["positive_control"] = positive_control(phone_raw, phone_terms)
        report["phone"] = phone
    else:
        say("  ! No phone recording arrived: only the desktop clip is cut.")
    for pattern in ("desktop-raw-*.mp4", "desktop-raw-*.json", "phone-raw-*"):
        keep_newest(paths.raw, pattern, RAW_KEEP * (2 if pattern.endswith("json") else 1))

    leaked = scrub_logs(paths, token or (FAKE_TOKEN if fake else ""))
    report.update(
        {
            "made": dt.datetime.now().isoformat(timespec="seconds"),
            "instance": {
                "port": paths.port,
                "root": str(paths.root),
                "home": str(paths.home),
                "code": commit,
                "warm_up": info,
            },
            "bot": {"username": f"@{bot_name}", "link": link}
            if telegram
            else {"username": "none (Telegram off)", "link": ""},
            "answer_text": answer,
            "timeline_s": {k: round(v - timeline["take_start"], 2) for k, v in timeline.items()},
            "token_in_logs": leaked,
            "model_turns_take": 1,
        }
    )
    write_report(out, report)
    summary(report)
    return 0


def positive_control(raw: Path, terms: list[tuple[str, str]]) -> dict[str, Any]:
    """The made-up video's Control Center carries TEST_NAME: the reading must find it there."""
    if not ocr_available():
        return {"checked": False}
    with tempfile.TemporaryDirectory(prefix="tgtake-") as tmp:
        png = Path(tmp) / "cc.png"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "1.0",
                "-i",
                str(raw),
                "-frames:v",
                "1",
                str(png),
            ]
        )
        text = read_text(png).lower()
    return {"checked": True, "found_in_raw": TEST_NAME.lower() in text}


# --------------------------------------------------------------------------
# What it writes
# --------------------------------------------------------------------------


def write_report(out: Path, report: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "telegram-take.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "telegram-notes.md").write_text(notes_text(report), encoding="utf-8")


def _findings(found: list[dict[str, Any]]) -> str:
    return ", ".join(f"{x['kind']} at {x['second']} s" for x in found)


def _privacy_line(p: dict[str, Any]) -> str:
    if not p.get("checked"):
        return "not run (" + str(p.get("why") or "no OCR") + "); look at the sheet yourself."
    found = p.get("findings") or []
    return (
        f"macOS text recognition read {p['stills']} stills (every {p['every_s']} s,"
        f" {p['lines_read']} lines) for {p['terms']} words (account, computer and Telegram"
        " names, the profile) and e-mail addresses: "
        + ("nothing found." if not found else "FOUND " + _findings(found) + ".")
    )


def _moving(m: dict[str, Any]) -> int:
    return round(100 * (m.get("changed_share") or 0))


def _clip_lines(name: str, c: dict[str, Any]) -> list[str]:
    m, cut_ = c["measure"], c["cut"]
    frames = c.get("raw_frames") or {}
    width, height = (m.get("size") or ["?", "?"])[:2]
    raw_w, raw_h = c["raw_size"][:2]
    lines = [
        f"### {name}",
        "",
        f"- `{Path(c['master']).name}`: {width} x {height}, {FPS} fps, {m.get('seconds')} s,"
        f" {m.get('megabytes')} MB, H.264 yuv420p, no sound. Sheet: `{Path(c['sheet']).name}`"
        f" ({c.get('sheet_stills')} stills, one a second).",
        f"- Raw: `{c['raw']}`, {c['raw_seconds']} s, {raw_w} x {raw_h}, {c.get('raw_codec')},"
        f" {frames.get('frames')} frames, mean {frames.get('mean_fps')} fps"
        + (", variable frame rate" if frames.get("variable") else "")
        + f", longest gap {frames.get('longest_gap_s')} s"
        + (", with a sound track (dropped)" if c.get("raw_audio") else "")
        + ".",
        f"- Found in the raw: {json.dumps(c['events'])}.",
        f"- Kept {cut_['kept']} s; cut out {cut_['removed'] or 'nothing'} with dissolves of"
        f" {cut_['dissolve_s']} s; speed {cut_['speed']}; {cut_['length_s']} s long.",
        f"- Movement: {_moving(m)} % of the frames differ from the one before; per second"
        f" {m.get('changed_per_second')}; lowest full second {m.get('lowest_full_second')} of"
        f" {FPS}; longest standstill {m.get('longest_standstill_s')} s at"
        f" {m.get('longest_standstill_at_s')} s.",
        f"- Privacy: {_privacy_line(c['privacy'])}",
    ]
    if "footage" in c:
        fo = c["footage"]
        lines.append(
            f"- Footage: {fo['frames']} screencast frames over {fo['seconds']} s; where something"
            f" moved they came at a median {fo['moving_fps_median']} fps; longest gap"
            f" {fo['longest_gap_s']} s (the screencast sends a frame only when the picture"
            " changes)."
        )
    if "positive_control" in c:
        pc = c["positive_control"]
        held = any(x["kind"] == "test name" for x in (c["privacy"].get("findings") or []))
        lines.append(
            "- Check of the check: the made-up Control Center carries a fictional name; the"
            f" reading found it in the raw: {pc.get('found_in_raw')}, and the cut clip holds"
            f" it: {held}."
        )
    return [*lines, ""]


def notes_text(report: dict[str, Any]) -> str:
    inst = report.get("instance") or {}
    warm = inst.get("warm_up") or {}
    tl = report.get("timeline_s") or {}
    dry, fake = bool(report.get("dry_run")), bool(report.get("fake_telegram"))
    bot = report["bot"]["username"]
    if not dry:
        how = f"sent from Telegram on the phone to the demo bot {bot}"
        lead = ""
    elif fake:
        how = f"sent by a made-up Telegram user to the stand-in bot {bot}"
        lead = (
            " A DRY RUN: no person and no phone. The message came through a local stand-in"
            " for the Telegram Bot API into the instance's real Telegram channel, and the"
            " phone clip is made up."
        )
    else:
        how = "sent through the instance's own chat API (Telegram was off)"
        lead = (
            " A DRY RUN: no person and no phone. The message entered through the instance's"
            " own chat API, the call the Telegram bridge makes, and the phone clip is made up."
        )
    answer = (report.get("answer_text") or "").strip()
    lines = [
        "# Telegram clip: notes written by telegram_take.py",
        "",
        f"Written {report.get('made')}." + lead,
        "",
        "## What it shows",
        "",
        f'- The message, {how}: "{report.get("message_typed") or report.get("sentence")}"',
        f'- {ASSISTANT}\'s answer in the desktop conversation: "{answer}"',
    ]
    if report.get("telegram_reply"):
        lines.append(f'- What the bot sent back to the chat: "{report["telegram_reply"]}"')
    lines += [
        "- The phone clip: "
        + (
            "the chat with the bot, the sentence typed and sent, the wait cut out, the answer."
            if not dry
            else "made up by the script (a drawn chat), only to test the cut."
        ),
        "- The desktop clip: the conversation with the assistant in the instance, the message"
        " arriving, the assistant at work (the wait cut out), the answer.",
        "",
        "## When (seconds from the take's start)",
        "",
        f"- {json.dumps(tl)}",
        "",
        "## The clips",
        "",
    ]
    if report.get("phone"):
        lines += _clip_lines("Phone (`telegram-phone-master.mp4`)", report["phone"])
    else:
        lines += [
            "### Phone",
            "",
            "- No phone recording arrived: cut it with `telegram_take.py cut phone <file>`.",
            "",
        ]
    lines += _clip_lines("Desktop (`telegram-desktop-master.mp4`)", report["desktop"])
    lines += [
        "## How it was made",
        "",
        f"- A throwaway instance on port {inst.get('port')} ({inst.get('root')}, home"
        f" {inst.get('home')}), code {str(inst.get('code'))[:10]} copied out of the repository"
        " so that it stands still. Started by `scripts/readme_demo/demo-instance.sh` with a"
        " clean environment (`USER`/`LOGNAME` set, nothing of the calling session), its own"
        " data folder, config and credential file; never the person's own app.",
        f"- Warm-up (not filmed, {warm.get('at')}): record.cjs `DEMO_PARTS=setup,warmup`"
        f" (first-run setup naming the assistant {ASSISTANT}, the trailhead and ledger"
        f" projects, two coding threads and a coding agent started by {ASSISTANT}), then"
        f' "{WARM_LINE}" {warm.get("lead_turns")} turns of {ASSISTANT} on'
        f" {warm.get('lead_model')}, {warm.get('threads')} coding threads.",
    ]
    if not dry:
        lines.append(
            "- Telegram: the instance's own channel, its token only in the instance's"
            " environment (`TELEGRAM_BOT_TOKEN`) and in a 0600 file of the instance's folder,"
            " the channel switched on by `JARVIS__INTEGRATIONS__TELEGRAM__ENABLED=true`. The"
            " first private sender within the pairing window became the owner (kept in the"
            " instance's config)."
        )
    elif fake:
        lines.append(
            "- Telegram: the instance's own channel, switched on by"
            " `JARVIS__INTEGRATIONS__TELEGRAM__ENABLED=true` with a made-up token, talking to a"
            " local stand-in for the Bot API (python-telegram-bot pointed at it by a"
            " sitecustomize on the instance's PYTHONPATH; no product code changed). The"
            " stand-in user paired with /start, then sent the sentence; the bridge sent the"
            f" answer back. Calls seen: {', '.join(report.get('fake_calls') or [])}."
        )
    else:
        lines.append("- Telegram: off (no token), as the dry run without a stand-in runs.")
    sent = (
        " (estimated: the instance logs no line when it sends)"
        if report.get("answer_sent_estimated")
        else ""
    )
    lines += [
        f"- Desktop filmed with the DevTools screencast of a headless Chrome, {WINDOW} at scale"
        f" {SCALE}, at most {FPS} fps, from two seconds before the message arrived until"
        f" {HOLD:.0f} s after the answer went to Telegram{sent}. No pointer: nobody is at the"
        f' desk. The Telegram sender\'s names are replaced by "{PERSONA[0]} {PERSONA[1]}" in what'
        " the page draws, if they show.",
        "- The cut, by the picture: still stretches longer than about a second leave with a"
        f" dissolve of {DISSOLVE} s ({KEEP_AFTER} s kept before it, {KEEP_BEFORE} s after);"
        " the phone recording starts and ends where the chat app's title bar is on screen"
        " (Control Center left out); typing plays at the speed it was typed.",
        f"- Model turns: {report.get('model_turns_take')} for this take.",
        f"- The token in the instance's logs: {report.get('token_in_logs')} times"
        + (" (rewritten)." if report.get("token_in_logs") else " (none)."),
        "",
        "## Look at it yourself",
        "",
        "- The sheets: text recognition misses small or faint text.",
        "- The answer must be a real test run: it should say how many tests ran.",
        "- The desktop clip is short: while the assistant works the conversation draws no"
        " steps, only typing dots and a status line in the panel, so the wait is cut. To show"
        " more of it: `telegram_take.py cut desktop <raw> --no-auto-remove --speed 1.25`, or"
        " `--remove FROM-TO` over part of the wait.",
        "",
    ]
    return "\n".join(lines)


def summary(report: dict[str, Any]) -> None:
    say()
    say("Done")
    for key, name in (("phone", "phone clip"), ("desktop", "desktop clip")):
        c = report.get(key)
        if not c:
            item(name, "none")
            continue
        m = c["measure"]
        found = c["privacy"].get("findings") or []
        item(
            name,
            f"{c['master']} ({c['cut']['length_s']} s, {_moving(m)} % moving frames,"
            f" longest standstill {m.get('longest_standstill_s')} s)",
        )
        if c["privacy"].get("checked"):
            item("", "privacy: " + ("nothing found" if not found else "CHECK " + _findings(found)))
    folder = Path(report["desktop"]["master"]).parent
    item("notes", str(folder / "telegram-notes.md"))
    say()
    say("Tell the lead (copy these lines):")
    phone = report.get("phone")
    desk = report["desktop"]
    dry = " (DRY RUN)" if report.get("dry_run") else ""
    say(
        f"  Telegram take ready{dry}: {folder}/telegram-phone-master.mp4"
        f" ({phone['cut']['length_s'] if phone else '-'} s, portrait) and"
        f" telegram-desktop-master.mp4 ({desk['cut']['length_s']} s, 1920 x 1080), sheets,"
        " telegram-take.json and telegram-notes.md beside them."
    )
    answer = (report.get("answer_text") or "").strip()[:200]
    bot = report["bot"]["username"]
    sent = report.get("message_typed") or report.get("sentence")
    say(f'  Bot {bot}; message "{sent}"; answer: "{answer}"')
    for key in ("phone", "desktop"):
        c = report.get(key)
        if not c:
            continue
        m = c["measure"]
        found = c["privacy"].get("findings") or []
        if not c["privacy"].get("checked"):
            reading = "not run."
        else:
            reading = "nothing found." if not found else "found " + _findings(found) + "."
        say(
            f"  {key}: cut {c['cut']['kept']} of {Path(c['raw']).name}; {_moving(m)} % moving"
            f" frames, longest standstill {m.get('longest_standstill_s')} s; privacy reading:"
            f" {reading}"
        )


# --------------------------------------------------------------------------
# selftest: the channel without a model
# --------------------------------------------------------------------------


def selftest(args: argparse.Namespace) -> int:
    base = make_paths(args)
    paths = Paths(
        root=base.root / "selftest",
        home=base.root / "selftest-home",
        port=base.port + 1,
        out=base.out,
        downloads=base.downloads,
    )
    say("Self-test of the Telegram channel (no model turns, no person)")
    need_tools()
    check_paths(base)
    check_paths(paths)
    code = ensure_code(base, False, args.bundle)
    # The self-test instance runs the same copy of the code.
    if paths.code.exists() or paths.code.is_symlink():
        if paths.code.is_symlink() or paths.code.is_file():
            paths.code.unlink()
        else:
            shutil.rmtree(paths.code)
    paths.code.symlink_to(base.code)
    instance = Instance(paths, args.python)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        say(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))

    made_up = "123456789:AAH" + "x" * 32
    _SECRETS.extend([made_up, FAKE_TOKEN])
    try:
        # 1. The script's own check of a token Telegram does not know.
        try:
            BotApi(made_up).call("getMe")
            check("a made-up token is refused by Telegram (getMe)", False, "Telegram accepted it")
        except TelegramError as exc:
            check(
                "a made-up token is refused by Telegram (getMe)",
                exc.code == 401 and "[token]" not in str(exc) and made_up not in str(exc),
                f"{exc.code} {exc}",
            )
        # 2. No token: the channel stays off.
        instance.start(keep=False, label="selftest-off")
        time.sleep(4)
        row = instance.telegram_row()
        failed = channel_failures(instance.log_text())
        check(
            "no token: the channel is off",
            not row.get("connected") and not failed,
            "connected"
            if row.get("connected")
            else (
                "not connected" + (f", but {failed[0][:80]}" if failed else ", no channel error")
            ),
        )
        instance.stop()
        # 3. A token Telegram rejects: the instance says so honestly.
        instance.start(keep=True, telegram=Telegram(token=made_up), label="selftest-invalid")
        end = time.time() + 60
        failed = []
        while time.time() < end and not failed:
            failed = channel_failures(instance.log_text())
            time.sleep(1)
        raw_log = instance.log.read_text(encoding="utf-8", errors="replace") if instance.log else ""
        check(
            "a rejected token: the channel says why",
            bool(failed)
            and "invalid" in failed[0].lower()
            and made_up not in raw_log
            and not instance.telegram_row().get("connected"),
            (failed[0][:140] if failed else "no failure logged"),
        )
        instance.stop()
        # 4. The stand-in Bot API: connected, paired by /start, kept after a restart.
        fake = FakeBotApi().start()
        shim = paths.work / "fake-telegram"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "sitecustomize.py").write_text(SHIM, encoding="utf-8")
        telegram = Telegram(token=FAKE_TOKEN, fake_url=fake.url, shim=shim)
        try:
            instance.start(keep=True, telegram=telegram, label="selftest-fake")
            row = instance.wait_channel(90)
            check(
                "the stand-in bot connects",
                row.get("handle") == "@nova_demo_bot",
                str(row.get("handle")),
            )
            fake.send_from(FAKE_OWNER, "/start")
            end = time.time() + 30
            while time.time() < end and not (
                instance.owner_ids() and fake.sent_to(FAKE_OWNER["id"])
            ):
                time.sleep(0.3)
            replies = fake.sent_to(FAKE_OWNER["id"])
            check(
                "/start pairs the first sender and is answered",
                instance.owner_ids() == [FAKE_OWNER["id"]] and bool(replies),
                (replies[0]["text"][:70] if replies else "no reply"),
            )
            mark = time.time()
            instance.stop()
            confirmed = [name for at, name in fake.calls if at > mark and name == "getUpdates"]
            instance.start(keep=True, telegram=telegram, label="selftest-restart")
            instance.wait_channel(90)
            check(
                "a restart keeps the owner",
                FAKE_OWNER["id"] in instance.owner_ids(),
                f"allowed_user_ids has {len(instance.owner_ids())} id(s)",
            )
            again = [m for m in fake.sent_to(FAKE_OWNER["id"]) if m["at"] > mark]
            check(
                "the /start is not answered a second time after the restart",
                not again,
                f"{len(confirmed)} getUpdates while stopping",
            )
            fake.send_from(FAKE_STRANGER, "/start")
            time.sleep(4)
            check(
                "a second sender is not answered",
                not fake.sent_to(FAKE_STRANGER["id"])
                and FAKE_STRANGER["id"] not in instance.owner_ids(),
            )
            chat = BotApi(FAKE_TOKEN, fake.url.rstrip("/")).call(
                "getChat", chat_id=FAKE_OWNER["id"]
            )
            check(
                "getChat names the sender (for the scrub)",
                chat.get("first_name") == FAKE_OWNER["first_name"],
            )
        finally:
            instance.stop()
            fake.stop()
        leaks = scrub_logs(paths, FAKE_TOKEN) + scrub_logs(paths, made_up)
        check("no token in the instance's logs", leaks == 0, f"{leaks} found")
    finally:
        instance.stop()
    failed_count = sum(1 for _, ok, _ in results if not ok)
    say()
    say(f"{len(results) - failed_count} of {len(results)} checks passed (code {code[:10]}).")
    return 1 if failed_count else 0


# --------------------------------------------------------------------------
# cut and stop
# --------------------------------------------------------------------------


def recut(args: argparse.Namespace) -> int:
    paths = make_paths(args)
    raw: Path = args.raw
    if not raw.exists():
        raise Stop(f"{raw} does not exist.")
    out = args.out
    need_tools()
    marks: dict[str, float] = {}
    if args.kind == "desktop":
        side = raw.with_suffix(".marks.json")
        if side.exists():
            marks = json.loads(side.read_text(encoding="utf-8"))
    report_path = out / "telegram-take.json"
    report: dict[str, Any] = {}
    if report_path.exists():
        with contextlib.suppress(ValueError):
            report = json.loads(report_path.read_text(encoding="utf-8"))
    owner_names: dict[str, str] = {}
    token = read_secret_file(paths.token_file)
    if token:
        _SECRETS.append(token)
    if token and paths.owner_file.exists():
        with contextlib.suppress(OSError, ValueError, TelegramError):
            owner = json.loads(paths.owner_file.read_text(encoding="utf-8"))
            chat = BotApi(token).call("getChat", chat_id=int(owner["user_id"])) or {}
            owner_names = {
                k: str(chat.get(k) or "") for k in ("first_name", "last_name", "username")
            }
    terms = sensitive_terms(owner_names)
    clip = cut_clip(
        args.kind,
        raw,
        out / f"telegram-{args.kind}-master.mp4",
        out / f"telegram-{args.kind}-sheet.png",
        terms,
        marks,
        args,
        lock_enabled=not args.no_lock,
    )
    if args.kind == "desktop" and report.get("desktop", {}).get("footage"):
        clip["footage"] = report["desktop"]["footage"]
    report[args.kind] = clip
    report.setdefault("bot", {"username": "?", "link": ""})
    report.setdefault("made", dt.datetime.now().isoformat(timespec="seconds"))
    if "desktop" in report:
        write_report(out, report)
        summary(report)
    else:
        (out / "telegram-take.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        say(f"  {clip['master']}: {clip['cut']['length_s']} s")
    return 0


def stop_command(args: argparse.Namespace) -> int:
    paths = make_paths(args)
    instance = Instance(paths, args.python)
    pid = instance._pid_from_file()
    if not pid:
        say("No demo instance of this script is running.")
        return 0
    instance._end(pid)
    paths.pid_file.unlink(missing_ok=True)
    say(f"Stopped the demo instance on port {paths.port} (its state is kept in {paths.root}).")
    return 0


def make_paths(args: argparse.Namespace) -> Paths:
    return Paths(
        root=Path(args.root).expanduser(),
        home=Path(args.home).expanduser(),
        port=int(args.port),
        out=Path(args.out).expanduser(),
        downloads=Path(args.downloads).expanduser(),
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        default=str(ROOT_DEFAULT),
        help="the demo instance's folder: its state, the "
        "warm-up copy, the token file, logs (default %(default)s)",
    )
    common.add_argument(
        "--home",
        default=str(HOME_DEFAULT),
        help="the demo instance's home folder, with the sample projects (default %(default)s)",
    )
    common.add_argument(
        "--port", type=int, default=PORT, help="the demo instance's port (default %(default)s)"
    )
    common.add_argument(
        "--out", default=str(OUT_DIR), help="where the clips go (default %(default)s)"
    )
    common.add_argument(
        "--downloads",
        default=str(Path.home() / "Downloads"),
        help="where the AirDropped recording lands (default %(default)s)",
    )
    common.add_argument(
        "--python",
        default=sys.executable,
        help="the Python the instance runs on (default: this one)",
    )
    common.add_argument(
        "--bundle",
        type=Path,
        default=None,
        help="a built frontend bundle (default: the repository's dodaios/ui/web/dist)",
    )
    common.add_argument(
        "--no-lock", action="store_true", help="ignore the film lock of other recorders"
    )
    if argv[:1] == ["cut"]:
        parser = argparse.ArgumentParser(
            prog="telegram_take.py cut",
            parents=[common],
            description="Cut a raw recording of a take again.",
        )
        parser.add_argument("kind", choices=("phone", "desktop"))
        parser.add_argument(
            "raw", type=Path, help="phone-raw-*.mov/mp4 or desktop-raw-*.mp4 in telegram-raw/"
        )
        parser.add_argument(
            "--start", type=float, default=None, help="second of the raw recording to start at"
        )
        parser.add_argument(
            "--end", type=float, default=None, help="second of the raw recording to end at"
        )
        parser.add_argument(
            "--remove",
            action="append",
            default=[],
            metavar="FROM-TO",
            help="cut this out instead of the waits found (repeatable)",
        )
        parser.add_argument("--no-auto-remove", action="store_true", help="cut out no wait")
        parser.add_argument(
            "--speed", type=float, default=None, help=f"desktop: play faster, at most {SPEED_MAX}"
        )
        args = parser.parse_args(argv[1:])
        args.out = Path(args.out).expanduser()
        if args.speed is not None and not 0.5 <= args.speed <= SPEED_MAX:
            parser.error(f"--speed must be between 0.5 and {SPEED_MAX}")
        handler = recut
    elif argv[:1] in (["selftest"], ["stop"]):
        parser = argparse.ArgumentParser(
            prog=f"telegram_take.py {argv[0]}",
            parents=[common],
            description=(
                "Check the instance's Telegram channel without a model: no "
                "token, a rejected token, pairing, a restart."
                if argv[0] == "selftest"
                else "Stop a demo instance this script left running."
            ),
        )
        args = parser.parse_args(argv[1:])
        handler = selftest if argv[0] == "selftest" else stop_command
    else:
        parser = argparse.ArgumentParser(
            prog="telegram_take.py",
            parents=[common],
            description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="everything that needs no person: a "
            "stand-in message, a made-up phone video; the clips go to <out>/telegram-dry-run/",
        )
        parser.add_argument(
            "--fake-telegram",
            action="store_true",
            help="with --dry-run: send the message "
            "through a local stand-in for the Telegram Bot API, into the real channel",
        )
        parser.add_argument(
            "--new-token", action="store_true", help="ask for a bot token even if one is kept"
        )
        parser.add_argument(
            "--fresh", action="store_true", help="copy the code again and redo the warm-up"
        )
        parser.add_argument(
            "--keep-running", action="store_true", help="leave the instance running afterwards"
        )
        parser.add_argument(
            "--sentence", default=SENTENCE, help="what is sent (default: %(default)s)"
        )
        args = parser.parse_args(argv)
        handler = run_take
    try:
        return handler(args)
    except Stop as exc:
        say(f"\nStopped: {exc}")
        return 1
    except KeyboardInterrupt:
        say("\nStopped.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
