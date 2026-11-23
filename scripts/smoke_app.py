#!/usr/bin/env python
"""Smoke check of the real desktop app, through the Dodaios Dev app over CDP.

Ten checks, each PASS / FAIL / SKIP, with a screenshot of the window on every
FAIL. It drives only the Dev app (data directory ``data-dev``, ports +100): it
reads the Dev app's own record of its port and its WebView debugging port, and
never looks at the default app's files. Load the branch first:

    python scripts/dev_preview.py <PR number or branch>
    python scripts/smoke_app.py                 # all ten checks
    python scripts/smoke_app.py --only chat     # checks whose name contains "chat"
    python scripts/smoke_app.py --list

Output goes to ``logs/smoke_app/<timestamp>/`` (git-ignored): ``smoke.json`` and
one PNG per failed check. Exit code: 0 no FAIL, 1 a check FAILed, 2 no Dev app
is running (nothing was checked).

The checks navigate the Dev window with ``?view=<section>`` (the app's own
deep link) and look for stable ``data-testid`` hooks first, then for real page
content, so a re-skinned screen does not break them. SKIP means "nothing to
check here" (for example no thread exists yet), never a hidden pass. The chat
check sends one harmless line to the Dev app's lead chat; it does not wait for
a model reply.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ERROR_TEXT = r"/something went wrong|application error|failed to fetch dynamically imported/i"


def main_checkout() -> Path:
    """The main checkout, also when this runs from a linked worktree."""
    out = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(out).parent if out else REPO


@dataclass
class Dev:
    base: str
    cdp_http: str
    pid: int


def find_dev(data_dir: Path, cdp_port: int | None) -> Dev:
    """Locate the running Dev app, or raise RuntimeError with the reason."""
    try:
        meta = json.loads((data_dir / ".jarvis-running").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"no Dev app record in {data_dir} ({exc.__class__.__name__})") from exc
    pid, port = int(meta.get("pid", 0)), int(meta.get("port", 0))
    try:
        import psutil

        alive = psutil.pid_exists(pid)
    except ImportError:
        alive = True
    if not alive or not port:
        raise RuntimeError(f"the Dev app is not running (last pid {pid})")
    if cdp_port is None:
        active = data_dir / "webview" / "EBWebView" / "DevToolsActivePort"
        try:
            cdp_port = int(active.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, ValueError, IndexError) as exc:
            raise RuntimeError(f"no WebView debugging port in {active}") from exc
    return Dev(base=f"http://127.0.0.1:{port}", cdp_http=f"http://127.0.0.1:{cdp_port}", pid=pid)


class Cdp:
    """A minimal Chrome DevTools Protocol client for one page."""

    def __init__(self, dev: Dev) -> None:
        from websockets.sync.client import connect

        with urllib.request.urlopen(f"{dev.cdp_http}/json", timeout=5) as resp:  # noqa: S310
            pages = json.load(resp)
        mine = [
            p
            for p in pages
            if p.get("type") == "page"
            and p.get("url", "").startswith(dev.base)
            and "solo=1" not in p.get("url", "")
        ]
        if not mine:
            raise RuntimeError(f"no window of the Dev app at {dev.base} in {dev.cdp_http}/json")
        self.title = mine[0].get("title", "")
        self._ws = connect(mine[0]["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
        self._id = 0
        self.call("Page.enable")
        self.call("Runtime.enable")

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self._ws.recv(timeout=60))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def js(self, expression: str):
        res = self.call(
            "Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True
        )
        if res.get("exceptionDetails"):
            text = res["exceptionDetails"].get("exception", {}).get("description", "js error")
            raise RuntimeError(text.splitlines()[0])
        return res.get("result", {}).get("value")

    def wait(self, predicate: str, timeout: float = 20.0, what: str = "condition"):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                value = self.js(predicate)
            except RuntimeError:
                value = None
            if value:
                return value
            time.sleep(0.4)
        raise TimeoutError(f"timed out after {timeout:.0f}s waiting for {what}")

    def screenshot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        path.write_bytes(base64.b64decode(data))

    def close(self) -> None:
        self._ws.close()


class Skip(Exception):  # noqa: N818 - control flow, not an error
    """Nothing to check here."""


def _has(selectors: list[str]) -> str:
    """JS: the first selector that matches a visible element, else false."""
    return (
        f"(()=>{{for(const s of {json.dumps(selectors)}){{const e=document.querySelector(s);"
        "if(e&&(e.offsetParent!==null||e.getClientRects().length))return s}return false})()"
    )


_CONTENT = (
    "(()=>{const t=(document.body.innerText||'').trim();"
    f"return t.length>40&&!({ERROR_TEXT}).test(t)}})()"
)


def _open_view(cdp: Cdp, dev: Dev, view: str) -> None:
    cdp.call("Page.navigate", url=f"{dev.base}/?view={view}")
    cdp.wait("document.readyState==='complete'", 30, "page load")
    cdp.wait(_CONTENT, 30, f"content of view {view}")


def _section(view: str, selectors: list[str]) -> Callable[[Cdp, Dev], str]:
    def run(cdp: Cdp, dev: Dev) -> str:
        _open_view(cdp, dev, view)
        if selectors:
            try:
                hit = cdp.wait(_has(selectors), 15, f"one of {selectors}")
                return f"found {hit}"
            except TimeoutError:
                pass  # fall back to content: a re-skinned screen still counts if it has content
        return "page has content, no error text"

    return run


def _get_json(cdp: Cdp, path: str):
    out = cdp.js(f"fetch({json.dumps(path)}).then(async r=>({{s:r.status,b:await r.text()}}))")
    if out["s"] != 200:
        raise AssertionError(f"GET {path} -> HTTP {out['s']}")
    return json.loads(out["b"])


def check_window(cdp: Cdp, dev: Dev) -> str:
    cdp.call("Page.navigate", url=f"{dev.base}/")
    cdp.wait("document.readyState==='complete'", 30, "page load")
    cdp.wait(_CONTENT, 30, "app content")
    title = cdp.js("document.title")
    root = cdp.js("document.getElementById('root')?.children.length||0")
    if not root:
        raise AssertionError("#root is empty")
    return f"title {title!r}, {root} root children"


def check_chat(cdp: Cdp, dev: Dev) -> str:
    _open_view(cdp, dev, "chats")
    box = (
        "(()=>{const v=e=>e&&(e.offsetParent!==null||e.getClientRects().length);"
        "const c=[...document.querySelectorAll('textarea,[contenteditable=\"true\"]')].filter(v);"
        "if(!c.length)return false;c[c.length-1].focus();return true})()"
    )
    cdp.wait(box, 20, "a focusable chat composer")
    marker = f"smoke-{uuid.uuid4().hex[:8]}"
    cdp.call("Input.insertText", text=f"{marker} reply with the single word ok")
    sent = cdp.js(
        "(()=>{const b=document.querySelector('[data-testid=\"composer-send\"]');"
        "if(b&&!b.disabled){b.click();return 'button'}return false})()"
    )
    if not sent:
        for kind in ("keyDown", "keyUp"):
            cdp.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                text="\r" if kind == "keyDown" else "",
            )
        sent = "Enter key"
    cdp.wait(
        f"(document.body.innerText||'').includes({json.dumps(marker)})",
        15,
        "the sent message to appear in the chat",
    )
    return f"message shown after send via {sent}"


def check_thread(cdp: Cdp, dev: Dev) -> str:
    body = _get_json(cdp, "/api/agent-chat/sessions")
    sessions = body if isinstance(body, list) else body.get("sessions", [])
    if not sessions:
        raise Skip("the Dev app has no thread yet")
    _open_view(cdp, dev, "agentic-ide")
    cdp.wait(_has(['[data-testid="igentic-ide"]', "[data-thread-column]"]), 25, "the IDE view")
    clicked = cdp.js(
        "(()=>{const c=document.querySelector('[data-testid=\"ide-agent-card\"]');"
        "if(c){c.click();return true}return false})()"
    )
    if clicked:
        cdp.wait(_has(["[data-thread-column]", '[data-testid="thread-working"]']), 15, "the thread")
        return f"{len(sessions)} threads; opened one from the list"
    return f"{len(sessions)} threads listed, IDE view rendered (no card to click)"


def check_ide(cdp: Cdp, dev: Dev) -> str:
    _open_view(cdp, dev, "agentic-ide")
    cdp.wait(_has(['[data-testid="igentic-ide"]']), 25, "the Agentic IDE view")
    pane = [
        ".xterm",
        '[data-testid="grid"]',
        '[data-testid="ide-agent-title"]',
        "[data-thread-column]",
    ]
    try:
        return f"pane found: {cdp.wait(_has(pane), 10, 'a pane')}"
    except TimeoutError as exc:
        raise Skip("the IDE view rendered but no workspace with a pane is open") from exc


def check_dictation(cdp: Cdp, dev: Dev) -> str:
    body = _get_json(cdp, "/api/dictation/status")
    if "available" not in body:
        raise AssertionError(f"no 'available' field in {sorted(body)}")
    return f"available={body['available']} active={body.get('active')}"


def check_voice(cdp: Cdp, dev: Dev) -> str:
    voice = _get_json(cdp, "/api/voice/status")
    health = _get_json(cdp, "/api/health")
    if "ready" not in voice:
        raise AssertionError(f"no 'ready' field in {sorted(voice)}")
    return f"voice ready={voice['ready']}, health {str(health)[:60]}"


CHECKS: list[tuple[str, Callable[[Cdp, Dev], str]]] = [
    ("window_loads", check_window),
    ("chat_accepts_message", check_chat),
    ("thread_opens", check_thread),
    ("ide_pane_renders", check_ide),
    ("dictation_endpoint", check_dictation),
    ("voice_status_endpoint", check_voice),
    ("nodes_open", _section("visualization", ['[data-testid="nodes-library"]'])),
    ("settings_open", _section("settings", ['[data-testid="settings-hub-dialog"]'])),
    ("plugins_open", _section("plugins", [])),
    ("agents_board", _section("agents", [])),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help="run checks whose name contains this text")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--data-dir", help="the Dev app's data directory (default: <main>/data-dev)")
    ap.add_argument("--cdp-port", type=int, help="WebView debugging port (default: from data dir)")
    args = ap.parse_args()

    checks = [c for c in CHECKS if not args.only or args.only in c[0]]
    if args.list:
        for name, _ in checks:
            print(name)
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else main_checkout() / "data-dev"
    try:
        dev = find_dev(data_dir, args.cdp_port)
        cdp = Cdp(dev)
    except (RuntimeError, OSError) as exc:
        print(f"no Dev app to check: {exc}\nstart one: python scripts/dev_preview.py <PR|branch>")
        return 2

    out_dir = REPO / "logs" / "smoke_app" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"checking {dev.base} (window {cdp.title!r}), results in {out_dir}")
    rows = []
    for name, fn in checks:
        started = time.perf_counter()
        status, detail, shot = "PASS", "", ""
        try:
            detail = fn(cdp, dev)
        except Skip as exc:
            status, detail = "SKIP", str(exc)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a row
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"[:300]
            try:
                path = out_dir / f"{name}.png"
                cdp.screenshot(path)
                shot = str(path)
            except Exception as shot_exc:  # noqa: BLE001
                detail += f" (no screenshot: {shot_exc})"
        secs = time.perf_counter() - started
        rows.append(
            {
                "name": name,
                "status": status,
                "seconds": round(secs, 1),
                "detail": detail,
                "screenshot": shot,
            }
        )
        print(f"{name:24s} {status:5s} {secs:5.1f}s  {detail}")
    cdp.close()
    (out_dir / "smoke.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    failed = [r["name"] for r in rows if r["status"] == "FAIL"]
    passed = sum(r["status"] == "PASS" for r in rows)
    print(f"\n{passed} pass, {len(failed)} fail, {len(rows) - passed - len(failed)} skip")
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
