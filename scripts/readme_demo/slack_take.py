#!/usr/bin/env python3
"""Record the README's Slack clip: a direct message from your phone, answered by the assistant.

    ~/Dodaios/.venv/bin/python scripts/readme_demo/slack_take.py
    ~/Dodaios/.venv/bin/python scripts/readme_demo/slack_take.py --dry-run [--fake-slack]
    ~/Dodaios/.venv/bin/python scripts/readme_demo/slack_take.py selftest
    ~/Dodaios/.venv/bin/python scripts/readme_demo/slack_take.py cut phone|desktop RAW [options]
    ~/Dodaios/.venv/bin/python scripts/readme_demo/slack_take.py stop

The Slack counterpart of telegram_take.py, and built on it: the instance, the
warm-up, the filming, the cut and the privacy reading are that script's. The
clip shows Slack as a real way to reach the assistant: a direct message typed
on a phone to the assistant's own Slack app, the assistant (Nova) doing a
small real task in a throwaway Dodaios instance, its answer in Slack, and the
same conversation in the desktop app.

Step 1, on the Mac. Run this script. It prints a link: Slack's "create app
from a manifest" page with the app "Nova" filled in. Open it, pick the demo
workspace, click Create, then Install to Workspace and Allow. Copy the Bot
User OAuth Token (OAuth & Permissions, xoxb-...). Then Basic Information >
App-Level Tokens > Generate Token and Scopes, with the scope
connections:write, and copy that token too (xapp-...). Paste both when the
script asks. They are not shown; they are kept in a file of the demo
instance's folder that only you can read, and handed to the instance in its
environment (never to the Keychain, never on a command line). The script
checks both with Slack, refuses a Slack app your own Dodaios app already
runs (two Socket Mode readers of one app split its messages), and prepares a
throwaway instance on port 47995 with sample projects and a short warm-up by
the model (the first time about five minutes).

Step 2, on the phone. When the script beeps, press Return with the phone in
your hand; then: open the Slack app, open the direct message with Nova, start
the screen recording, type and send

    Run the tests in trailhead and tell me if anything fails.

wait for the answer, stop the recording and AirDrop it to this Mac. The first
direct message pairs you as the app's owner (Nova answers it with one line
that says so, then with the answer).

Everything else is done here, as in telegram_take.py: the desktop filmed
while the message arrives and is answered, the AirDropped video picked up in
~/Downloads, both recordings cut by themselves. It writes into
~/Movies/Dodaios-Launch/v2/:

    slack-phone-master.mp4     the phone, portrait, H.264, 60 fps, no sound
    slack-desktop-master.mp4   the desktop, 1920 x 1080, H.264, 60 fps
    slack-phone-sheet.png      one still per second of each clip
    slack-desktop-sheet.png
    slack-take.json            what happened when, and how it was cut
    slack-notes.md             the same in words, with the privacy check
    slack-raw/                 the raw recordings, for another cut

Another take needs neither the app setup nor the warm-up nor the pairing
again: run the same command. The Slack names of the workspace's members (read
with the bot token) are replaced in the desktop's picture by "Alex Rivera",
and both clips are read by macOS's text recognition for names, the account
and computer names and e-mail addresses.

--dry-run does all that needs no person: the message enters through the
instance's own chat API, and the phone cut runs on a made-up video.
--fake-slack sends it through tests/fakes/slack_standin.py instead, a local
stand-in for Slack's Web API and Socket Mode, so the instance's real Slack
channel pairs, receives and answers. `selftest` checks the channel without a
model: no keys, a refused key, pairing by the first direct message, a
stranger ignored, a restart that keeps the owner.

Needs what telegram_take.py needs: macOS, ffmpeg, Node.js, Google Chrome,
Claude Code signed in, and the Python of the Dodaios environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import getpass
import json
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import telegram_take as tt  # noqa: E402

REPO = tt.REPO
# This checkout's dodaios and tests.fakes, not the installed copy (which may
# not have the Slack channel yet).
sys.path.insert(0, str(REPO))

Stop, say, item = tt.Stop, tt.say, tt.item
ROOT_DEFAULT = Path("/Users/Shared/slackdemo-root")
HOME_DEFAULT = Path("/Users/Shared/slackdemo")
PORT = 47995
ASSISTANT, PERSONA, SENTENCE = tt.ASSISTANT, tt.PERSONA, tt.SENTENCE
KEY_RE = re.compile(r"\b(?:xox[a-z]|xapp)-[A-Za-z0-9-]+")
#: The stand-in's people: a made-up owner (the name the scrub must replace) and a stranger.
FAKE_OWNER, FAKE_OWNER_DM = "U0OWNER001", "D0OWNERDM1"
FAKE_STRANGER, FAKE_STRANGER_DM = "U0OTHER001", "D0OTHERDM1"
#: Not a key Slack or the stand-in knows (split so secret scanners do not take it for one).
REFUSED_BOT = "xoxb" + "-000000000009-000000000009-RefusedKeyMadeUpForTheSelfTest"
tt.NAME_STOP.add("slack")

_tt_clean = tt._clean


def _clean(text: str) -> str:
    return KEY_RE.sub("[key]", _tt_clean(text))


# Everything telegram_take prints or reads from an instance log goes through
# this: no Slack key reaches the console, whatever its shape.
tt._clean = _clean


class Paths(tt.Paths):
    @property
    def keys_file(self) -> Path:
        return self.secrets / "slack-keys.json"

    @property
    def owner_file(self) -> Path:
        return self.secrets / "slack-owner.json"

    @property
    def raw(self) -> Path:
        return self.out / "slack-raw"


@dataclass
class Slack:
    """How the instance's Slack channel runs: its keys, the stand-in's address, the shim."""

    bot: str = ""
    app: str = ""
    api_base: str = ""
    shim: Path | None = None


class Instance(tt.Instance):
    """telegram_take's instance, with the Slack channel switched on through its environment."""

    def env(self, keep: bool, telegram: Any) -> dict[str, str]:
        env = super().env(keep, None)
        slack = telegram if isinstance(telegram, Slack) else None
        if slack is None:
            return env
        # The keys reach the instance only here: not in a file of the
        # repository, not on a command line.
        env["JARVIS__INTEGRATIONS__SLACK__ENABLED"] = "true"
        if slack.bot:
            env["SLACK_BOT_TOKEN"] = slack.bot
        if slack.app:
            env["SLACK_APP_TOKEN"] = slack.app
        if slack.api_base:
            env["JARVIS__INTEGRATIONS__SLACK__API_BASE_URL"] = slack.api_base
        if slack.shim is not None:
            env["PYTHONPATH"] += ":" + str(slack.shim)
        return env

    def slack_state(self) -> dict[str, Any]:
        state = self.get("/api/channels/slack")
        return state if isinstance(state, dict) else {}

    def slack_owner_ids(self) -> list[str]:
        try:
            import tomllib

            data = tomllib.loads(self.paths.config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        slack = (data.get("integrations") or {}).get("slack") or {}
        return [str(v) for v in slack.get("allowed_user_ids") or []]

    def wait_slack(self, timeout: float = 90.0) -> dict[str, Any]:
        """The channel's state once it runs and its Socket Mode link is up."""
        end = time.time() + timeout
        while time.time() < end:
            state = self.slack_state()
            if state.get("running") and state.get("link_up"):
                self.channel_since = time.time()
                return state
            if state.get("error") and not state.get("retrying") and not state.get("running"):
                raise Stop("The instance's Slack channel did not start: " + state["error"][:300])
            if not self.alive():
                raise Stop("The demo instance stopped:\n" + self.log_tail(12))
            time.sleep(1.0)
        raise Stop(f"The Slack channel was not up after {timeout:.0f} s:\n" + self.log_tail(10))

    def wait_slack_error(self, timeout: float = 60.0) -> dict[str, Any]:
        end = time.time() + timeout
        state: dict[str, Any] = {}
        while time.time() < end:
            state = self.slack_state()
            if state.get("error") or state.get("running"):
                return state
            time.sleep(1.0)
        return state


# --------------------------------------------------------------------------
# Slack (the demo app's keys only)
# --------------------------------------------------------------------------


def slack_call(method: str, token: str, base: str = "", **params: Any) -> dict[str, Any]:
    from dodaios.channels.slack_api import SlackApi

    async def go() -> dict[str, Any]:
        api = SlackApi(base)
        try:
            return await api.call(method, token, **params)
        finally:
            await api.aclose()

    return asyncio.run(go())


def check_pair(bot: str, app: str, base: str = "") -> Any:
    """``check_keys`` of the channel: both keys work and belong to one app (SlackKeys)."""
    from dodaios.channels.slack_api import SlackApi, check_keys

    async def go() -> Any:
        api = SlackApi(base)
        try:
            return await check_keys(bot, app, api=api)
        finally:
            await api.aclose()

    return asyncio.run(go())


def refuse_own_app(keys: Any) -> None:
    """Stop when the person's own app (or the Dev app) runs this Slack app (read-only GETs)."""
    for port in tt.OWN_APPS:
        state = tt.http_json(f"http://127.0.0.1:{port}/api/channels/slack", timeout=3)
        if not isinstance(state, dict) or not state.get("running"):
            continue
        theirs = str(state.get("app_id") or "")
        if (theirs and theirs == keys.app_id) or (
            not theirs and state.get("team_id") == keys.team_id
        ):
            raise Stop(
                f"Your own Dodaios app (port {port}) runs this Slack app already. Two Socket Mode"
                " readers of one app split its messages between them: create a second app for the"
                " demo with the link of step 1 (the same workspace is fine) and paste its keys"
                " (--new-keys), or disconnect Slack in your own app for the take."
            )


def read_keys(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(data.get(k) or "") for k in ("bot", "app")}


def obtain_keys(paths: Paths, new: bool) -> tuple[str, str, Any]:
    """The demo app's two keys and what Slack says about them (``SlackKeys``)."""
    from dodaios.channels.slack_api import SlackSetupError, create_app_url

    stored = {} if new else read_keys(paths.keys_file)
    if stored.get("bot") and stored.get("app"):
        tt._SECRETS.extend([stored["bot"], stored["app"]])
        try:
            keys = check_pair(stored["bot"], stored["app"])
            item("Slack app", f"{keys.bot_name or ASSISTANT} (the keys kept from the last take)")
            return stored["bot"], stored["app"], keys
        except SlackSetupError as exc:
            if exc.transient:
                raise Stop(f"Slack could not check the kept keys: {exc}") from None
            say(f"  The kept keys no longer work ({exc}) Paste new ones.")
    if not sys.stdin or not sys.stdin.isatty():
        raise Stop("No Slack keys yet, and no terminal to paste them into. Run this in Terminal.")
    say("  Step 1, on this Mac:")
    say("    a. Open this link (Slack's page to create an app from a manifest, filled in):")
    say(f"       {create_app_url(ASSISTANT)}")
    say("    b. Pick the demo workspace, Create, then Install to Workspace, then Allow.")
    say("    c. OAuth & Permissions: copy the Bot User OAuth Token (xoxb-...).")
    say("    d. Basic Information > App-Level Tokens > Generate Token and Scopes: any name,")
    say("       the scope connections:write, Generate; copy the token (xapp-...).")
    say("    e. Paste both below. They are not shown and never go to the Keychain.")
    for _ in range(3):
        bot = getpass.getpass("  Bot User OAuth Token (xoxb-..., not shown), then Return: ").strip()
        app = getpass.getpass("  App-Level Token (xapp-..., not shown), then Return: ").strip()
        if not bot or not app:
            continue
        tt._SECRETS.extend([bot, app])
        try:
            keys = check_pair(bot, app)
        except SlackSetupError as exc:
            if exc.transient:
                raise Stop(f"Slack could not check the keys: {exc}") from None
            say(f"  {exc} Copy both keys again (step 1, c and d).")
            continue
        tt.write_private(paths.keys_file, json.dumps({"bot": bot, "app": app}) + "\n")
        item("Slack app", f"{keys.bot_name or ASSISTANT} (keys kept in {paths.keys_file}, 0600)")
        return bot, app, keys
    raise Stop("No working pair of keys was pasted.")


def slack_names(token: str, base: str = "", user_ids: list[str] | None = None) -> list[str]:
    """The names of these members, or of every person in the workspace (for the scrub)."""
    try:
        if user_ids:
            people = [
                slack_call("users.info", token, base, user=uid).get("user") or {}
                for uid in user_ids
            ]
        else:
            people = [
                m
                for m in slack_call("users.list", token, base, limit=200).get("members") or []
                if not m.get("is_bot") and not m.get("deleted") and m.get("id") != "USLACKBOT"
            ]
    except Exception as exc:  # noqa: BLE001 - the privacy reading still runs
        say(f"  (Slack did not name the members: {type(exc).__name__}; the reading still runs)")
        return []
    names: list[str] = []
    for person in people:
        profile = person.get("profile") or {}
        for value in (
            person.get("real_name"),
            person.get("name"),
            profile.get("real_name"),
            profile.get("display_name"),
            profile.get("first_name"),
            profile.get("last_name"),
        ):
            value = " ".join(str(value or "").split())
            if len(value) >= 3 and value.lower() not in tt.NAME_STOP and value not in names:
                names.append(value)
    return names


def scrub_pairs(names: list[str]) -> str:
    """telegram-film.cjs's "text=replacement" lines: every name becomes the persona."""
    pairs: list[str] = []
    for name in sorted(names, key=len, reverse=True):
        parts = name.split()
        if len(parts) > 1:
            pairs.append(f"{name}={PERSONA[0]} {PERSONA[1]}")
            pairs += [f"{parts[0]}={PERSONA[0]}", f"{parts[-1]}={PERSONA[1]}"]
        else:
            pairs.append(f"{name}={PERSONA[2] if name.islower() else PERSONA[0]}")
    keep = [p for p in dict.fromkeys(pairs) if p.split("=")[0].lower() not in tt.NAME_STOP]
    return "\n".join(keep) + ("\n" if keep else "")


def slack_terms(names: list[str], profile: Any = None) -> list[tuple[str, str]]:
    extra = [("Slack name", n) for n in names]
    extra += [("Slack name", part) for n in names for part in re.split(r"[\s._'-]+", n)]
    return tt.sensitive_terms({}, extra, profile if isinstance(profile, dict) else None)


def set_slack_owner(config: Path, user_id: str) -> None:
    """Put the owner paired in an earlier take back into the instance's config."""
    import tomlkit

    doc = (
        tomlkit.parse(config.read_text(encoding="utf-8")) if config.exists() else tomlkit.document()
    )
    integrations = doc.get("integrations")
    if integrations is None:
        integrations = tomlkit.table()
        doc["integrations"] = integrations
    slack = integrations.get("slack")
    if slack is None:
        slack = tomlkit.table()
        integrations["slack"] = slack
    slack["allowed_user_ids"] = [user_id]
    config.write_text(tomlkit.dumps(doc), encoding="utf-8")


def slack_reply(token: str, user_id: str, after: float, cache: dict[str, str]) -> dict | None:
    """The app's first message in the owner's direct message since ``after`` (real Slack)."""
    try:
        if "dm" not in cache:
            opened = slack_call("conversations.open", token, users=user_id)
            cache["dm"] = str((opened.get("channel") or {}).get("id") or "")
        if not cache["dm"]:
            return None
        history = slack_call(
            "conversations.history", token, channel=cache["dm"], oldest=f"{after:.6f}", limit=20
        )
    except Exception:  # noqa: BLE001 - the time is estimated instead
        return None
    mine = [m for m in history.get("messages") or [] if m.get("bot_id")]
    return min(mine, key=lambda m: float(m.get("ts") or 0)) if mine else None


# --------------------------------------------------------------------------
# The stand-in, the entry point, the Keychain
# --------------------------------------------------------------------------


class StandIn:
    """tests/fakes/slack_standin.py's SlackStandIn on its own event loop, in a thread."""

    def __init__(self) -> None:
        from tests.fakes.slack_standin import Person, SlackStandIn

        self.slack = SlackStandIn(
            people={
                FAKE_OWNER: Person(FAKE_OWNER, tt.TEST_NAME, "en-US", FAKE_OWNER_DM),
                FAKE_STRANGER: Person(FAKE_STRANGER, "Orla Finch", "en-US", FAKE_STRANGER_DM),
            }
        )
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="slack-standin")
        self.thread.daemon = True
        self.thread.start()
        self.run(self.slack.start())
        tt._SECRETS.extend([self.slack.bot_token, self.slack.app_token])

    def run(self, coro: Any, timeout: float = 30.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def dm(self, user_id: str, text: str) -> None:
        """``user_id`` writes in their direct message with the app (on the open link)."""
        self.run(self.slack.wait_link(timeout=30))
        self.run(self.slack.dm(user_id, text))

    def posts_to(self, channel: str) -> list[dict[str, Any]]:
        return [p for p in list(self.slack.posts) if p.get("channel") == channel]

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.run(self.slack.stop(), 10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def entry_point_shim(paths: Paths, python: str) -> Path | None:
    """A throwaway dist-info that names the Slack channel, while the venv's metadata lacks it.

    pyproject.toml registers the channel; the installed metadata has it only
    after this branch is merged and the app reinstalled itself.
    """
    group = "jarvis.channel"
    with contextlib.suppress(OSError):
        manager = (paths.code / "dodaios" / "channels" / "manager.py").read_text(encoding="utf-8")
        found = re.search(r'PLUGIN_GROUP\s*=\s*"([^"]+)"', manager)
        group = found.group(1) if found else group
    probe = (
        "import importlib.metadata as m, sys\n"
        "print(any(e.name == 'slack' for e in m.entry_points(group=sys.argv[1])))"
    )
    if tt.run([python, "-I", "-c", probe, group], timeout=60).stdout.strip() == "True":
        return None
    folder = paths.work / "slack-entry-point"
    dist = folder / "slack_channel_shim-0.0.0.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: slack-channel-shim\nVersion: 0.0.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        f"[{group}]\nslack = dodaios.channels.slack:SlackChannel\n", encoding="utf-8"
    )
    return folder


def check_keychain_closed(paths: Paths) -> None:
    """The instance reads no Keychain item: get_secret asks the OS keyring before the
    environment, so the person's own Slack keys would beat the demo's."""
    script = paths.code / "scripts" / "readme_demo" / "demo-instance.sh"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    if "PYTHON_KEYRING_BACKEND" not in text or "keyring.backends.fail.Keyring" not in text:
        raise Stop(
            f"{script} does not switch the instance's keyring off, so the instance could read your"
            " own Slack keys from the Keychain before the demo's. Run this from a checkout whose"
            " demo-instance.sh sets PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring."
        )


def fresh_code(paths: Paths, args: argparse.Namespace) -> str:
    """The code copy; copied again when the checkout moved on (the warm-up stays)."""
    head = tt.run(["git", "-C", str(REPO), "rev-parse", "HEAD"]).stdout.strip()
    moved = bool(head) and tt.code_commit(paths.code) not in ("", head)
    commit = tt.ensure_code(paths, args.fresh or moved, args.bundle)
    item("code", f"{commit[:10]} (a copy in {paths.code}" + (", copied again)" if moved else ")"))
    check_keychain_closed(paths)
    return commit


# --------------------------------------------------------------------------
# The take
# --------------------------------------------------------------------------


def run_take(args: argparse.Namespace) -> int:
    dry, fake_mode = bool(args.dry_run), bool(args.fake_slack)
    if fake_mode and not dry:
        raise Stop("--fake-slack goes with --dry-run.")
    paths = make_paths(args)
    if dry:
        paths.out = paths.out / "slack-dry-run"
    out = paths.out
    say("Slack take for the README" + (" (dry run, no person needed)" if dry else ""))
    say()
    say("1. Checks")
    tt.need_tools()
    tt.check_paths(paths)
    if not tt.chrome_installed():
        raise Stop("Google Chrome is not installed; the desktop is filmed with it.")
    modules = tt.ensure_playwright()
    load, free = tt.machine_state(out)
    item("this Mac", f"load {load:.1f}, {free / 1024**3:.1f} GB free")
    if free < tt.MIN_FREE_BYTES:
        raise Stop("Less than 2 GB free on the disk: the desktop footage alone needs up to 1 GB.")
    if load > 6:
        say("  ! The Mac is busy: frames may come unevenly. Better when the load is under 5.")
    item("OCR (privacy check)", "macOS text recognition" if tt.ocr_available() else "missing")
    if not dry:
        tt.downloads_names(paths.downloads)  # macOS asks now, not after the take
        item("AirDrop arrives in", str(paths.downloads))
    bot = app = ""
    keys: Any = None
    if not dry:
        say()
        say("2. The demo Slack app")
        bot, app, keys = obtain_keys(paths, args.new_keys)
        refuse_own_app(keys)
        item("workspace", f"{keys.team_name} (app {keys.app_id})")
    commit = fresh_code(paths, args)
    shim = entry_point_shim(paths, args.python)
    item("channel entry point", "installed" if shim is None else f"a throwaway dist-info ({shim})")
    instance = Instance(paths, args.python)
    say()
    say("3. The demo instance")
    info = tt.warm_info(paths)
    if info is None or args.fresh:
        info = tt.warm_up(paths, instance, modules)
    else:
        item("warm-up", f"kept from {info.get('at')} ({info.get('lead_turns')} turns)")
    used = paths.state / ".slack-take-used"
    if used.exists() or not paths.config.exists():
        tt.restore_warm(paths)
        item("state", "back to the warm-up copy")
    used.write_text(dt.datetime.now().isoformat(), encoding="utf-8")
    owner: dict[str, Any] = {}
    if keys is not None and paths.owner_file.exists():
        with contextlib.suppress(OSError, ValueError):
            owner = json.loads(paths.owner_file.read_text(encoding="utf-8"))
    if keys is not None and owner.get("app_id") == keys.app_id and owner.get("user_id"):
        set_slack_owner(paths.config, str(owner["user_id"]))
        item("Slack owner", "paired in an earlier take (kept)")
    else:
        owner = {}

    standin: StandIn | None = None
    slack: Slack | None = None
    base = ""
    names: list[str] = []
    if fake_mode:
        standin = StandIn()
        base = standin.slack.api_base
        bot, app = standin.slack.bot_token, standin.slack.app_token
        slack = Slack(bot, app, base, shim)
        names = slack_names(bot, base, [FAKE_OWNER])
        item("Slack", f"the local stand-in at {base} (made-up owner and keys)")
    elif not dry:
        slack = Slack(bot, app, "", shim)
        names = slack_names(bot, "", [str(owner["user_id"])] if owner else None)
        item("names to replace", f"{len(names)} (of {'the owner' if owner else 'the workspace'})")
        say()
        tt.beep()
        if sys.stdin and sys.stdin.isatty():
            say("  Ready for step 2. Have your phone in your hand, then press Return here.")
            while not tt.wait_key(3600):
                pass
        else:
            say("  Ready for step 2 (no terminal to press Return in: going on).")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    take_dir = paths.work / f"desktop-{stamp}"
    scrub_file = paths.work / f"scrub-{stamp}.txt"
    tt.write_private(scrub_file, scrub_pairs(names))
    film: tt.Film | None = None
    lock = tt.FilmLock("slack_take.py (the desktop of the Slack take)", enabled=not args.no_lock)
    timeline: dict[str, float] = {}
    report: dict[str, Any] = {"dry_run": dry, "fake_slack": fake_mode, "sentence": args.sentence}
    answer, state, profile = "", {}, None
    try:
        instance.start(keep=True, telegram=slack, label="take")
        item("instance", f"{paths.origin}/ (Slack {'on' if slack else 'off'})")
        profile = instance.get("/api/profile")
        if slack:
            state = instance.wait_slack()
            if keys is not None and str(state.get("app_id") or "") not in ("", keys.app_id):
                raise Stop(
                    "The instance runs another Slack app than the keys pasted: it must not see"
                    " any Slack key but the demo's. Stop and look at the instance's environment."
                )
            item(
                "Slack channel",
                f"running as {state.get('bot_name') or '?'}; "
                + (
                    "owner known"
                    if state.get("owner_paired")
                    else f"pairing open for {state.get('pairing_seconds_left')} s"
                ),
            )
        film = tt.Film(paths, modules, take_dir, scrub_file)
        sid = instance.lead()["session_id"]
        baseline = max([e["seq"] for e in instance.events(sid, 5)] or [0])
        timeline["take_start"] = time.time()
        downloads_known = set() if dry else tt.downloads_names(paths.downloads)
        window = tt.pairing_window_s(paths)
        lock.take()
        film.command("arm", "armed")
        say()
        if dry:
            say("4. The take (a stand-in sends the message)")
            time.sleep(1.5)
            if standin is not None:
                standin.dm(FAKE_OWNER, args.sentence)
            elif not instance.send(
                "POST", f"/api/agent-chat/sessions/{sid}/messages", {"text": args.sentence}
            ):
                raise Stop("The instance did not take the stand-in message.")
        else:
            say("4. Step 2, on your phone (Do Not Disturb on, so no notice shows):")
            say(f"     a. Open the Slack app, then the direct message with {ASSISTANT}.")
            if owner:
                say("        (It knows you already. For a clean picture, clear the old messages.)")
            else:
                say("        Your first message pairs you. The line that says so comes in")
                say("        Slack's language: set it to English for the clip (Preferences >")
                say("        Language & region).")
            say("     b. Start the screen recording (Control Center, the record button),")
            say("        close Control Center.")
            say("     c. Type and send:")
            say(f"          \033[1m{args.sentence}\033[0m")
            say(f"     d. Wait for {ASSISTANT}'s answer, look at it for two seconds,")
            say("        stop the recording.")
            say("     e. Photos: the recording, Share, AirDrop, this Mac.")
            say("  This window follows along; nothing to do here.")
        message: dict[str, Any] | None = None
        reopened = 0
        deadline = time.time() + 45 * 60
        while message is None:
            if time.time() > deadline:
                raise Stop("No message arrived within 45 minutes. Run this again to retry.")
            ids = instance.slack_owner_ids() if slack else []
            if ids and not owner and "paired" not in timeline:
                timeline["paired"] = time.time()
            for event in tt.new_events(instance, sid, baseline):
                if event["kind"] == "user_message":
                    message = event
                    break
            if (
                message is None
                and not ids
                and slack is not None
                and standin is None
                and time.time() - instance.channel_since > window - 45
            ):
                # The channel lets a first sender pair only shortly after it starts.
                reopened += 1
                say("  Nobody wrote to the app yet; opening the pairing window again (a restart).")
                instance.stop()
                instance.start(keep=True, telegram=slack, label=f"take-reopen{reopened}")
                instance.wait_slack()
                film.command("reload", "ready", 120)
                say(f"  Ready again: send the sentence in the direct message with {ASSISTANT}.")
            time.sleep(0.25)
        arrived = message["ts_ms"] / 1000.0
        timeline["message"] = arrived
        film.command(f"record {arrived:.3f}", "recording")
        payload = message["payload"] or {}
        typed = str(payload.get("typed") or payload.get("text") or "")
        report["message_typed"] = typed
        item("message arrived", '"' + typed[:100] + '"')
        ids = instance.slack_owner_ids() if slack else []
        if ids and "paired" in timeline:
            item("paired", "the sender of the first direct message is the owner now")
            timeline["paired"] = min(timeline["paired"], arrived)
        if ids and not owner and keys is not None:
            owner = {"app_id": keys.app_id, "team_id": keys.team_id, "user_id": ids[0]}
            tt.write_private(paths.owner_file, json.dumps(owner) + "\n")
            more = [n for n in slack_names(bot, "", ids[:1]) if n not in names]
            if more:
                names += more
                tt.write_private(scrub_file, scrub_pairs(names))
                film.command(f"scrub {scrub_file}", "scrubbed")
        dm = FAKE_OWNER_DM
        posts_seen = len(standin.posts_to(dm)) if standin else 0
        if standin and posts_seen:
            report["slack_pairing_line"] = standin.posts_to(dm)[0].get("text", "")
        noticed: list[tuple[float, dict[str, Any]]] = []

        def look_posts() -> None:
            nonlocal posts_seen
            if standin is not None:
                posts = standin.posts_to(dm)
                noticed.extend((time.time(), p) for p in posts[posts_seen:])
                posts_seen = len(posts)

        turn_id = str(payload.get("turn_id") or "")
        finished = None
        end = time.time() + 15 * 60
        while finished is None:
            if time.time() > end:
                raise Stop(f"{ASSISTANT} was still working after 15 minutes.")
            events = tt.new_events(instance, sid, baseline)
            if not turn_id:
                turn_id = next(
                    (
                        str((e["payload"] or {}).get("turn_id") or "")
                        for e in events
                        if e["kind"] == "turn_started" and e["seq"] > message["seq"]
                    ),
                    "",
                )
            for event in events:
                if (
                    event["kind"] == "turn_finished"
                    and turn_id
                    and (event["payload"] or {}).get("turn_id") == turn_id
                ):
                    finished = event
            look_posts()
            time.sleep(0.3)
        timeline["answer_done"] = finished["ts_ms"] / 1000.0
        status = str((finished["payload"] or {}).get("status") or "")
        answer = tt.turn_text(tt.new_events(instance, sid, baseline, 400), turn_id)
        item(
            "answer",
            (f"({status}) " if status not in ("", "done", "completed") else "")
            + answer[:160].replace("\n", " "),
        )
        if not answer:
            say("  ! The turn ended without words: the take shows no answer. Run it again.")
        # The bridge posts the answer to Slack once the turn is over.
        sent_at = None
        cache: dict[str, str] = {}
        end = time.time() + (30 if slack else 0)
        while sent_at is None and time.time() < end:
            if standin is not None:
                look_posts()
                late = [x for x in noticed if x[0] >= timeline["answer_done"] - 0.5] or noticed
                if late:
                    sent_at, post = late[0]
                    report["slack_reply"] = post.get("text", "")
            elif slack is not None and owner:
                reply = slack_reply(bot, str(owner["user_id"]), arrived, cache)
                if reply and float(reply.get("ts") or 0) >= timeline["answer_done"] - 2:
                    sent_at = float(reply["ts"])
                    report["slack_reply"] = str(reply.get("text") or "")
                else:
                    time.sleep(1.2)
            time.sleep(0.2)
        if sent_at is None:
            sent_at = timeline["answer_done"] + (1.0 if slack else 0.0)
            report["answer_sent_estimated"] = bool(slack)
            if standin is not None:
                say("  ! The stand-in saw no answer posted to Slack within 30 s.")
        timeline["answer_sent"] = sent_at
        time.sleep(max(0.0, sent_at + tt.HOLD + 0.6 - time.time()))
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
        if standin is not None:
            report["standin_calls"] = sorted({c[0] for c in standin.slack.calls})
            report["standin_posts"] = [p.get("text", "") for p in standin.posts_to(FAKE_OWNER_DM)]
            standin.stop()
        scrub_file.unlink(missing_ok=True)
    say(
        "  The desktop is filmed; the demo instance "
        + ("still runs (--keep-running)." if args.keep_running else "is stopped (state kept).")
    )

    # ---- the clips --------------------------------------------------------
    say()
    say("5. The clips")
    paths.raw.mkdir(parents=True, exist_ok=True)
    desktop_raw = paths.raw / f"desktop-raw-{stamp}.mp4"
    footage = tt.frames_to_video(take_dir, desktop_raw)
    shutil.copy(take_dir / "take.json", paths.raw / f"desktop-raw-{stamp}.json")
    marks = {
        k: v - footage["t0"]
        for k, v in timeline.items()
        if k in ("message", "answer_done", "answer_sent", "paired")
    }
    desktop_raw.with_suffix(".marks.json").write_text(
        json.dumps(marks, indent=2) + "\n", encoding="utf-8"
    )
    shutil.rmtree(take_dir, ignore_errors=True)
    terms = slack_terms(names, profile)
    desktop = tt.cut_clip(
        "desktop",
        desktop_raw,
        out / "slack-desktop-master.mp4",
        out / "slack-desktop-sheet.png",
        terms,
        marks,
        lock_enabled=not args.no_lock,
    )
    desktop["footage"] = footage
    report["desktop"] = desktop

    phone_src: Path | None = None
    if dry:
        stand_in = paths.work / "stand-in-downloads"
        stand_in.mkdir(parents=True, exist_ok=True)
        made = paths.work / f"made-up-{stamp}.mov"
        reply = report.get("slack_reply") or answer or "All tests pass."
        report["made_up_phone"] = tt.made_up_phone_video(made, reply[:300], paths.work)
        known = {p.name for p in stand_in.iterdir()}
        since = time.time()

        def deliver() -> None:
            time.sleep(2.0)  # it arrives a moment later, as an AirDrop does
            shutil.copy(made, stand_in / f"ScreenRecording_{stamp}.MOV")

        threading.Thread(target=deliver, daemon=True).start()
        phone_src = tt.wait_for_video(stand_in, known, since, 60)
    else:
        say(f"  Waiting for the screen recording in {paths.downloads} (AirDrop it to this Mac).")
        say("  Ctrl-C stops waiting; cut it later with: slack_take.py cut phone <file>")
        try:
            phone_src = tt.wait_for_video(
                paths.downloads, downloads_known, timeline["take_start"], 45 * 60
            )
        except KeyboardInterrupt:
            phone_src = None
    if phone_src is not None:
        phone_raw = paths.raw / f"phone-raw-{stamp}{phone_src.suffix.lower()}"
        shutil.copy2(phone_src, phone_raw)
        item("phone recording", f"{phone_src.name} -> {phone_raw}")
        phone_terms = terms + ([("test name", tt.TEST_NAME.lower())] if dry else [])
        phone = tt.cut_clip(
            "phone",
            phone_raw,
            out / "slack-phone-master.mp4",
            out / "slack-phone-sheet.png",
            phone_terms,
            lock_enabled=not args.no_lock,
        )
        if dry:
            phone["positive_control"] = tt.positive_control(phone_raw, phone_terms)
        report["phone"] = phone
    else:
        say("  ! No phone recording arrived: only the desktop clip is cut.")
    for pattern in ("desktop-raw-*.mp4", "desktop-raw-*.json", "phone-raw-*"):
        tt.keep_newest(paths.raw, pattern, tt.RAW_KEEP * (2 if pattern.endswith("json") else 1))

    leaked = sum(tt.scrub_logs(paths, key) for key in (bot, app) if key)
    report.update(
        {
            "made": dt.datetime.now().isoformat(timespec="seconds"),
            "instance": {
                "port": paths.port,
                "root": str(paths.root),
                "home": str(paths.home),
                "code": commit,
                "warm_up": info,
                "entry_point_shim": shim is not None,
            },
            "slack": {
                "app": state.get("bot_name") or ("none (Slack off)" if not slack else "?"),
                "mode": "stand-in" if standin else ("real" if slack else "off"),
            },
            "answer_text": answer,
            "timeline_s": {k: round(v - timeline["take_start"], 2) for k, v in timeline.items()},
            "keys_in_logs": leaked,
            "model_turns_take": 1,
        }
    )
    write_report(out, report)
    summary(report)
    return 0


# --------------------------------------------------------------------------
# What it writes
# --------------------------------------------------------------------------


def write_report(out: Path, report: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "slack-take.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "slack-notes.md").write_text(notes_text(report), encoding="utf-8")


def clip_lines(name: str, clip: dict[str, Any]) -> list[str]:
    return [line.replace("Telegram", "Slack") for line in tt._clip_lines(name, clip)]


def notes_text(report: dict[str, Any]) -> str:
    inst = report.get("instance") or {}
    warm = inst.get("warm_up") or {}
    dry, fake = bool(report.get("dry_run")), bool(report.get("fake_slack"))
    if not dry:
        how, lead = "sent from the Slack app on the phone, in the direct message with the app", ""
    elif fake:
        how = "sent by a made-up Slack member through a local stand-in for Slack"
        lead = (
            " A DRY RUN: no person and no phone. The message came through"
            " tests/fakes/slack_standin.py (Web API and Socket Mode) into the instance's real"
            " Slack channel, and the phone clip is made up."
        )
    else:
        how = "sent through the instance's own chat API (Slack was off)"
        lead = (
            " A DRY RUN: no person and no phone. The message entered through the instance's"
            " own chat API, and the phone clip is made up."
        )
    lines = [
        "# Slack clip: notes written by slack_take.py",
        "",
        f"Written {report.get('made')}." + lead,
        "",
        "## What it shows",
        "",
        f'- The message, {how}: "{report.get("message_typed") or report.get("sentence")}"',
        f'- {ASSISTANT}\'s answer in the desktop conversation: "{report.get("answer_text")}"',
    ]
    if report.get("slack_pairing_line"):
        lines.append(f'- The pairing line the app posted first: "{report["slack_pairing_line"]}"')
    if report.get("slack_reply"):
        lines.append(f'- What the app posted back in Slack: "{report["slack_reply"]}"')
    lines += [
        "- The phone clip: "
        + (
            "the direct message with the app, the sentence typed and sent, the wait cut,"
            " the answer."
            if not dry
            else "made up by telegram_take.py (its drawn chat), only to test the cut."
        ),
        "- The desktop clip: the conversation with the assistant in the instance, the message"
        " arriving, the assistant at work (the wait cut out), the answer.",
        "",
        "## When (seconds from the take's start)",
        "",
        f"- {json.dumps(report.get('timeline_s') or {})}",
        "",
        "## The clips",
        "",
    ]
    if report.get("phone"):
        lines += clip_lines("Phone (`slack-phone-master.mp4`)", report["phone"])
    else:
        lines += ["### Phone", "", "- None arrived: `slack_take.py cut phone <file>`.", ""]
    lines += clip_lines("Desktop (`slack-desktop-master.mp4`)", report["desktop"])
    slack_line = {
        "real": "the instance's own channel, its keys only in the instance's environment"
        " (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) and in a 0600 file of the instance's folder;"
        " the instance's keyring is switched off, so no Keychain item is read. The first"
        " direct message within the pairing window made its sender the owner.",
        "stand-in": "the instance's own channel against tests/fakes/slack_standin.py with its"
        " made-up keys (`JARVIS__INTEGRATIONS__SLACK__API_BASE_URL`). The made-up owner's"
        " first direct message paired and was the sentence; the bridge posted the answer."
        f" Calls seen: {', '.join(report.get('standin_calls') or [])}.",
        "off": "off (no keys), as the dry run without a stand-in runs.",
    }[(report.get("slack") or {}).get("mode", "off")]
    shim = " The channel's entry point came from a throwaway dist-info on the instance's"
    lines += [
        "## How it was made",
        "",
        f"- A throwaway instance on port {inst.get('port')} ({inst.get('root')}, home"
        f" {inst.get('home')}), code {str(inst.get('code'))[:10]} copied out of the repository,"
        " started by `scripts/readme_demo/demo-instance.sh`; never the person's own app."
        + (
            shim + " PYTHONPATH (the venv is not reinstalled yet)."
            if inst.get("entry_point_shim")
            else ""
        ),
        f"- Warm-up (not filmed, {warm.get('at')}): telegram_take.py's warm-up,"
        f" {warm.get('lead_turns')} turns of {ASSISTANT} on {warm.get('lead_model')},"
        f" {warm.get('threads')} coding threads.",
        "- Slack: " + slack_line,
        f"- Desktop filmed with telegram-film.cjs (DevTools screencast of a headless Chrome,"
        f" {tt.WINDOW} at scale {tt.SCALE}, at most {tt.FPS} fps) until {tt.HOLD:.0f} s after"
        " the answer went to Slack"
        + (" (estimated)" if report.get("answer_sent_estimated") else "")
        + f'. Slack names are replaced by "{PERSONA[0]} {PERSONA[1]}" in what the page draws.',
        f"- Slack keys in the instance's logs: {report.get('keys_in_logs')}"
        + (" (rewritten)." if report.get("keys_in_logs") else " (none)."),
        "",
        "## Look at it yourself",
        "",
        "- The sheets: text recognition misses small or faint text.",
        "- The answer must be a real test run: it should say how many tests ran.",
        "- More of the wait: `slack_take.py cut desktop <raw> --no-auto-remove --speed 1.25`.",
        "",
    ]
    return "\n".join(lines)


def summary(report: dict[str, Any]) -> None:
    say()
    say("Done")
    folder = Path(report["desktop"]["master"]).parent
    for key in ("phone", "desktop"):
        clip = report.get(key)
        if not clip:
            item(f"{key} clip", "none")
            continue
        found = clip["privacy"].get("findings") or []
        reading = (
            "not run"
            if not clip["privacy"].get("checked")
            else ("nothing found" if not found else "CHECK " + tt._findings(found))
        )
        item(f"{key} clip", f"{clip['master']} ({clip['cut']['length_s']} s; privacy: {reading})")
    if report.get("fake_slack"):
        ok = bool(report.get("slack_reply")) and bool(report.get("slack_pairing_line"))
        item(
            "stand-in Slack",
            ("PASS" if ok else "FAIL")
            + f": paired ({bool(report.get('slack_pairing_line'))}), answer posted to Slack"
            f" ({bool(report.get('slack_reply'))})",
        )
    control = (report.get("phone") or {}).get("positive_control")
    if control:
        held = any(
            x["kind"] == "test name" for x in report["phone"]["privacy"].get("findings") or []
        )
        item(
            "check of the check",
            ("PASS" if control.get("found_in_raw") and not held else "FAIL")
            + f": the made-up name read in the raw ({control.get('found_in_raw')}),"
            f" left in the cut clip ({held})",
        )
    item("keys in logs", str(report.get("keys_in_logs")))
    item("notes", str(folder / "slack-notes.md"))
    say()
    say("Tell the lead (copy these lines):")
    phone, desk = report.get("phone"), report["desktop"]
    say(
        f"  Slack take ready{' (DRY RUN)' if report.get('dry_run') else ''}:"
        f" {folder}/slack-phone-master.mp4 ({phone['cut']['length_s'] if phone else '-'} s,"
        f" portrait) and slack-desktop-master.mp4 ({desk['cut']['length_s']} s, 1920 x 1080),"
        " sheets, slack-take.json and slack-notes.md beside them."
    )
    answer = (report.get("answer_text") or "").strip()[:200]
    say(f'  Message "{report.get("message_typed") or report.get("sentence")}"; answer: "{answer}"')
    if report.get("slack_reply"):
        say(f'  Posted in Slack: "{str(report["slack_reply"])[:200]}"')


# --------------------------------------------------------------------------
# selftest: the channel without a model
# --------------------------------------------------------------------------


def selftest(args: argparse.Namespace) -> int:
    from dodaios.channels.slack_api import SlackSetupError

    base = make_paths(args)
    paths = Paths(
        root=base.root / "selftest",
        home=base.root / "selftest-home",
        port=base.port + 1,
        out=base.out,
        downloads=base.downloads,
    )
    say("Self-test of the Slack channel (no model turns, no person)")
    tt.need_tools()
    tt.check_paths(base)
    tt.check_paths(paths)
    args.fresh = False
    code = fresh_code(base, args)
    if paths.code.is_symlink() or paths.code.is_file():
        paths.code.unlink()
    elif paths.code.exists():
        shutil.rmtree(paths.code)
    paths.code.symlink_to(base.code)  # the self-test runs the take's copy of the code
    shim = entry_point_shim(paths, args.python)
    item("channel entry point", "installed" if shim is None else "a throwaway dist-info")
    instance = Instance(paths, args.python)
    results: list[tuple[str, str, str]] = []

    def check(name: str, ok: Any, detail: str = "", note: bool = False) -> None:
        mark = "NOTE" if note else ("PASS" if ok else "FAIL")
        results.append((name, mark, detail))
        say(f"  {mark}  {name}" + (f": {detail}" if detail else ""))

    def no_key(*texts: Any) -> bool:
        return not any(KEY_RE.search(json.dumps(t, default=str)) for t in texts)

    tt._SECRETS.append(REFUSED_BOT)
    standin = StandIn()
    fake = Slack(standin.slack.bot_token, standin.slack.app_token, standin.slack.api_base, shim)
    try:
        # 1. The script's own check of pasted keys, against the stand-in.
        try:
            check_pair(REFUSED_BOT, fake.app, fake.api_base)
            check("check_keys refuses a made-up bot key", False, "accepted")
        except SlackSetupError as exc:
            check(
                "check_keys refuses a made-up bot key",
                exc.code == "bot_token_rejected" and no_key(str(exc)),
                str(exc),
            )
        keys = check_pair(fake.bot, fake.app, fake.api_base)
        check("check_keys accepts the stand-in's pair", keys.app_id == standin.slack.app_id)
        # 2. No keys: the channel does not run, and says why without a key.
        instance.start(keep=False, telegram=Slack(api_base=fake.api_base, shim=shim), label="off")
        state = instance.wait_slack_error()
        check(
            "no keys: the channel does not run and the app says why",
            not state.get("running") and "missing" in str(state.get("error")) and no_key(state),
            str(state.get("error"))[:120] or "no reason given",
        )
        log = instance.log_text()
        named = bool(re.search(r"slack[^\n]*(missing|start failed)", log, re.IGNORECASE))
        check(
            "no keys: the instance's console log names the reason",
            named,
            "yes" if named else "no Slack line in the console log",
            note=not named,
        )
        instance.stop()
        # 3. A refused key: the channel says so, without the key.
        refused = Slack(REFUSED_BOT, fake.app, fake.api_base, shim)
        instance.start(keep=True, telegram=refused, label="refused")
        state = instance.wait_slack_error()
        raw_log = instance.log.read_text(encoding="utf-8", errors="replace") if instance.log else ""
        check(
            "a refused bot key: the channel does not run and says why",
            not state.get("running")
            and "refused" in str(state.get("error"))
            and REFUSED_BOT not in raw_log
            and no_key(state),
            str(state.get("error"))[:120] or "no reason given",
        )
        instance.stop()
        # 4. The stand-in's keys: running, paired by the first direct message.
        instance.start(keep=True, telegram=fake, label="fake")
        state = instance.wait_slack()
        check(
            "the stand-in's keys: running, pairing open",
            state.get("app_id") == standin.slack.app_id and bool(state.get("pairing_open")),
            f"app {state.get('app_id')}, pairing {state.get('pairing_seconds_left')} s",
        )
        # A direct message that is only the app's mention pairs, and starts no turn.
        empty = f"<@{standin.slack.bot_user_id}>"
        standin.dm(FAKE_OWNER, empty)
        end = time.time() + 30
        while time.time() < end and not (
            instance.slack_owner_ids() and standin.posts_to(FAKE_OWNER_DM)
        ):
            time.sleep(0.3)
        posts = standin.posts_to(FAKE_OWNER_DM)
        check(
            "the first direct message pairs its sender, with one line",
            instance.slack_owner_ids() == [FAKE_OWNER] and len(posts) == 1,
            (posts[0].get("text", "")[:70] if posts else "no line posted"),
        )
        standin.dm(FAKE_STRANGER, "Hello, who are you?")
        time.sleep(4)
        check(
            "a stranger gets nothing back and is not paired",
            not standin.posts_to(FAKE_STRANGER_DM) and instance.slack_owner_ids() == [FAKE_OWNER],
        )
        # 5. A restart keeps the owner, and pairs nobody again.
        instance.stop()
        instance.start(keep=True, telegram=fake, label="restart")
        state = instance.wait_slack()
        standin.dm(FAKE_OWNER, empty)
        time.sleep(3)
        check(
            "a restart keeps the owner, pairing stays closed",
            instance.slack_owner_ids() == [FAKE_OWNER]
            and state.get("owner_paired")
            and not state.get("pairing_open")
            and len(standin.posts_to(FAKE_OWNER_DM)) == 1,
            f"{len(instance.slack_owner_ids())} owner(s),"
            f" {len(standin.posts_to(FAKE_OWNER_DM))} line(s) posted",
        )
        check(
            "users.info names the owner (for the scrub)",
            slack_names(fake.bot, fake.api_base, [FAKE_OWNER]) == [tt.TEST_NAME],
        )
        check("the state the app shows carries no key", no_key(state))
    finally:
        instance.stop()
        standin.stop()
    leaks = sum(tt.scrub_logs(paths, k) for k in (fake.bot, fake.app, REFUSED_BOT))
    check("no key in the instance's logs", leaks == 0, f"{leaks} found")
    failed = sum(1 for _, mark, _ in results if mark == "FAIL")
    graded = sum(1 for _, mark, _ in results if mark != "NOTE")
    say()
    say(f"{graded - failed} of {graded} checks passed (code {code[:10]}).")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# cut and stop
# --------------------------------------------------------------------------


def recut(args: argparse.Namespace) -> int:
    paths = make_paths(args)
    raw: Path = args.raw
    if not raw.exists():
        raise Stop(f"{raw} does not exist.")
    out = args.out
    tt.need_tools()
    marks: dict[str, float] = {}
    side = raw.with_suffix(".marks.json")
    if args.kind == "desktop" and side.exists():
        marks = json.loads(side.read_text(encoding="utf-8"))
    report_path = out / "slack-take.json"
    report: dict[str, Any] = {}
    if report_path.exists():
        with contextlib.suppress(ValueError):
            report = json.loads(report_path.read_text(encoding="utf-8"))
    names: list[str] = []
    bot = read_keys(paths.keys_file).get("bot", "")
    if bot:
        tt._SECRETS.append(bot)
        owner: dict[str, Any] = {}
        with contextlib.suppress(OSError, ValueError):
            owner = json.loads(paths.owner_file.read_text(encoding="utf-8"))
        names = slack_names(bot, "", [str(owner["user_id"])] if owner.get("user_id") else None)
    clip = tt.cut_clip(
        args.kind,
        raw,
        out / f"slack-{args.kind}-master.mp4",
        out / f"slack-{args.kind}-sheet.png",
        slack_terms(names),
        marks,
        args,
        lock_enabled=not args.no_lock,
    )
    if args.kind == "desktop" and report.get("desktop", {}).get("footage"):
        clip["footage"] = report["desktop"]["footage"]
    report[args.kind] = clip
    report.setdefault("made", dt.datetime.now().isoformat(timespec="seconds"))
    if "desktop" in report:
        write_report(out, report)
        summary(report)
    else:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        say(f"  {clip['master']}: {clip['cut']['length_s']} s")
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
    common.add_argument("--root", default=str(ROOT_DEFAULT), help="the instance's folder")
    common.add_argument("--home", default=str(HOME_DEFAULT), help="the instance's home folder")
    common.add_argument("--port", type=int, default=PORT, help="the instance's port")
    common.add_argument("--out", default=str(tt.OUT_DIR), help="where the clips go")
    common.add_argument(
        "--downloads", default=str(Path.home() / "Downloads"), help="where AirDrop saves"
    )
    common.add_argument("--python", default=sys.executable, help="the instance's Python")
    common.add_argument(
        "--bundle", type=Path, default=None, help="a built frontend bundle (default: dist)"
    )
    common.add_argument("--no-lock", action="store_true", help="ignore other recorders' lock")
    if argv[:1] == ["cut"]:
        parser = argparse.ArgumentParser(
            prog="slack_take.py cut", parents=[common], description="Cut a raw recording again."
        )
        parser.add_argument("kind", choices=("phone", "desktop"))
        parser.add_argument("raw", type=Path, help="phone-raw-* or desktop-raw-*.mp4 in slack-raw/")
        parser.add_argument("--start", type=float, default=None, help="second to start at")
        parser.add_argument("--end", type=float, default=None, help="second to end at")
        parser.add_argument(
            "--remove", action="append", default=[], metavar="FROM-TO", help="cut this out"
        )
        parser.add_argument("--no-auto-remove", action="store_true", help="cut out no wait")
        parser.add_argument("--speed", type=float, default=None, help="desktop: play faster")
        args = parser.parse_args(argv[1:])
        args.out = Path(args.out).expanduser()
        if args.speed is not None and not 0.5 <= args.speed <= tt.SPEED_MAX:
            parser.error(f"--speed must be between 0.5 and {tt.SPEED_MAX}")
        handler = recut
    elif argv[:1] in (["selftest"], ["stop"]):
        parser = argparse.ArgumentParser(
            prog=f"slack_take.py {argv[0]}",
            parents=[common],
            description="Check the instance's Slack channel without a model."
            if argv[0] == "selftest"
            else "Stop a demo instance this script left running.",
        )
        args = parser.parse_args(argv[1:])
        handler = selftest if argv[0] == "selftest" else tt.stop_command
    else:
        parser = argparse.ArgumentParser(
            prog="slack_take.py",
            parents=[common],
            description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--dry-run", action="store_true", help="everything without a person")
        parser.add_argument(
            "--fake-slack",
            action="store_true",
            help="with --dry-run: the message comes through a local stand-in for Slack",
        )
        parser.add_argument("--new-keys", action="store_true", help="ask for the keys again")
        parser.add_argument("--fresh", action="store_true", help="copy the code, redo the warm-up")
        parser.add_argument("--keep-running", action="store_true", help="leave the instance up")
        parser.add_argument("--sentence", default=SENTENCE, help="what is sent")
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
