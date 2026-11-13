"""Consent walls, a hung click and an unreadable model reply in the real worker.

Run with the isolated Browser-Use runtime's Python (see the consent tests at
the end of ``test_browser_live.py``). Every site is a fixture served through
Playwright routes, so nothing here reaches the internet. Prints one JSON line
with the observations; the test asserts on it.
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]

FLIGHTS = "https://www.google.com/travel/flights?hl=de&q=MUC%20DXB"
# Where Google's 302 for a visitor without a consent cookie leads.
CONSENT = "https://consent.google.com/m?continue=" + quote(FLIGHTS, safe="") + "&gl=DE&hl=de"

# The structure of Google's consent page: two forms that post to /save, each
# with one submit button. Hidden inputs carry the choice.
CONSENT_PAGE = """<!doctype html><html lang="de"><title>Bevor Sie zu Google weitergehen</title>
<body><div class="consent"><h1>Bevor Sie zu Google weitergehen</h1>
<p>Wir verwenden Cookies und Daten, um Dienste bereitzustellen und personalisierte Werbung
anzuzeigen.</p>
<form action="https://consent.google.com/save" method="POST">
  <input type="hidden" name="continue" value="{target}">
  <input type="hidden" name="set_eom" value="true">
  <button type="submit" aria-label="Alle ablehnen"><span>Alle ablehnen</span></button>
</form>
<form action="https://consent.google.com/save" method="POST">
  <input type="hidden" name="continue" value="{target}">
  <input type="hidden" name="set_eom" value="false">
  <button type="submit" aria-label="Alle akzeptieren"><span>Alle akzeptieren</span></button>
</form>
<a href="https://consent.google.com/ml">Weitere Optionen</a></div></body></html>"""

FLIGHTS_PAGE = """<!doctype html><title>Google Flights fixture</title>
<h1>Flights fixture MUC DXB</h1>
<button aria-label="slow-probe" onclick="window.slowClicked=true">Slow button</button>"""

ONETRUST_PAGE = """<!doctype html><title>News</title><h1>News fixture</h1>
<div id="onetrust-banner-sdk" role="dialog" style="position:fixed;bottom:0;left:0;right:0;
background:#fff;padding:20px"><p>Wir und unsere Partner verwenden Cookies.</p>
<button id="onetrust-accept-btn-handler" onclick="window.choice='accept';this.parentNode.remove()">
Alle akzeptieren</button>
<button id="onetrust-reject-all-handler" onclick="window.choice='reject';this.parentNode.remove()">
Alle ablehnen</button></div>"""

SOURCEPOINT_PARENT = """<!doctype html><title>Shop</title><h1>Shop fixture</h1>
<iframe id="sp_message_iframe_1" src="https://cdn.privacy-mgmt.com/index.html?message_id=1"
 style="position:fixed;inset:10%;width:80%;height:80%;border:0"></iframe>
<script>addEventListener("message", (e) => { window.choice = e.data;
document.getElementById("sp_message_iframe_1").remove(); });</script>"""

SOURCEPOINT_FRAME = """<!doctype html><title>Privacy</title><body>
<p>We and our partners use cookies and similar tracking technologies.</p>
<button class="message-component sp_choice_type_11" onclick="parent.postMessage('accept','*')">
Accept all</button>
<button class="message-component sp_choice_type_13" onclick="parent.postMessage('reject','*')">
Reject all</button></body>"""

SHADOW_PAGE = """<!doctype html><title>App</title><h1>App fixture</h1>
<div id="usercentrics-root"></div>
<script>
const root = document.getElementById("usercentrics-root").attachShadow({mode: "open"});
root.innerHTML = `<div role="dialog" aria-modal="true" style="position:fixed;bottom:0;padding:16px;
background:#fff"><p>We use cookies to personalise content and ads.</p>
<button onclick="window.choice='accept'">Accept all</button>
<button onclick="window.choice='necessary'">Use necessary cookies only</button></div>`;
</script>"""

ACCEPT_ONLY_PAGE = """<!doctype html><title>Blog</title><h1>Blog fixture</h1>
<div role="dialog" class="cookie-notice"><p>Diese Seite verwendet Cookies.</p>
<button onclick="window.choice='accept'">Akzeptieren</button></div>"""

PAYWALL_PAGE = """<!doctype html><title>Magazin</title><h1>Magazin fixture</h1>
<div id="didomi-host" role="dialog"><p>Wir und unsere Partner nutzen Cookies und Tracking.</p>
<button id="didomi-notice-agree-button" onclick="window.choice='accept'">Akzeptieren</button>
<button id="didomi-notice-disagree-button" onclick="window.choice='subscribe'">
Ablehnen und abonnieren</button></div>"""

OAUTH_PAGE = """<!doctype html><title>Authorize</title>
<div role="dialog" id="consent"><p>Fixture App wants to access your account.</p>
<button onclick="window.choice='deny'">Deny</button>
<button onclick="window.choice='allow'">Allow</button></div>"""

SITES = {
    "https://news.example.org/": ONETRUST_PAGE,
    "https://shop.example.org/": SOURCEPOINT_PARENT,
    "https://app.example.org/": SHADOW_PAGE,
    "https://blog.example.org/": ACCEPT_ONLY_PAGE,
    "https://magazin.example.org/": PAYWALL_PAGE,
    "https://auth.example.org/": OAUTH_PAGE,
}


class Google:
    """Google's redirect to its consent page and the form post back."""

    def __init__(self) -> None:
        self.choice = ""

    async def handle(self, route) -> None:
        request = route.request
        url = request.url
        if url.startswith("https://cdn.privacy-mgmt.com/"):
            await route.fulfill(status=200, content_type="text/html", body=SOURCEPOINT_FRAME)
            return
        base = url.split("?")[0].split("#")[0]
        if base in SITES:
            await route.fulfill(status=200, content_type="text/html", body=SITES[base])
            return
        if url.startswith("https://consent.google.com/save") and request.method == "POST":
            form = parse_qs(request.post_data or "")
            self.choice = "reject" if form.get("set_eom") == ["true"] else "accept"
            # Google answers with a 303 to the flights page. Chromium drops a
            # navigation whose redirect comes from a fulfilled route, so the
            # fixture answers with the destination page itself.
            await route.fulfill(status=200, content_type="text/html", body=FLIGHTS_PAGE)
            return
        if url.startswith("https://consent.google.com/m"):
            target = unquote(parse_qs(urlsplit(url).query)["continue"][0])
            page = CONSENT_PAGE.replace("{target}", target)
            await route.fulfill(status=200, content_type="text/html", body=page)
            return
        await route.fulfill(status=204, body="")


async def check_sites(worker, google, observations) -> None:
    from consent_walls import dismiss_consent

    page = worker.page
    results = {}
    for url in SITES:
        await page.goto(url, wait_until="load")
        await asyncio.sleep(0.3)  # The fixture banners render from inline scripts.
        started = time.monotonic()
        hits = await dismiss_consent(page)
        results[url] = {
            "hits": [hit["text"] for hit in hits],
            "choice": await page.evaluate("window.choice || ''"),
            "seconds": round(time.monotonic() - started, 2),
        }
    observations["sites"] = results


async def main():
    sys.path.insert(0, str(ROOT / "dodaios/society/browser"))
    output = sys.stdout
    import live_runner

    events = []
    live_runner.emit = lambda kind, **data: events.append({"kind": kind, **data})
    live_runner.CLICK_TIMEOUT_S = 2.0
    worker = live_runner.Worker()
    google = Google()
    observations: dict = {}
    profile = Path(sys.argv[2])
    await worker.start(
        {
            "profile_dir": str(profile),
            "workspace": str(profile / "workspace"),
            "executable": sys.argv[1],
            "allowed_domains": [],
        }
    )
    try:
        # Registered after the worker's own route, so it answers first.
        await worker.context.route(re.compile(r"^https://"), google.handle)
        await check_sites(worker, google, observations)

        # A click that never returns: the worker must fail it fast.
        from browser_use.tools.registry.service import Registry

        execute = Registry.execute_action

        async def hanging(self, action_name, *args, **kwargs):
            if action_name == "click":
                await asyncio.sleep(3600)
            return await execute(self, action_name, *args, **kwargs)

        Registry.execute_action = hanging

        calls = []

        async def fake_rpc(kind, payload):
            if kind == "action":
                return {"ok": True, "permit": f"permit-{len(events)}"}
            text = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for row in payload["messages"]
                for part in (
                    row["content"] if isinstance(row["content"], list) else [row["content"]]
                )
            )
            calls.append(text)
            if len(calls) == 1:
                observations["first_view_has_consent"] = "Alle ablehnen" in text
                observations["first_view_has_flights"] = "Slow button" in text
                index = re.search(r"\[(\d+)\]<button[^\n]*slow-probe", text)
                action = {"click": {"index": int(index.group(1)) if index else 1}}
                body = {
                    "evaluation_previous_goal": "Start",
                    "memory": "On the flights fixture",
                    "next_goal": "Click the slow button",
                    "action": [action],
                }
                # Prose and a fenced block: the reply must still be read.
                reply = "Here is my next step:\n```json\n" + json.dumps(body) + "\n```"
                return {"ok": True, "text": reply, "usage": {}}
            if len(calls) == 2:
                observations["second_view_reports_timeout"] = "timed out" in text
                return {"ok": True, "text": "The click timed out, so I will stop.", "usage": {}}
            observations["reask_seen"] = "could not be used" in text
            body = {
                "evaluation_previous_goal": "The click timed out",
                "memory": "Fixture read",
                "next_goal": "Finish",
                "action": [{"done": {"text": "fixture done", "success": True}}],
            }
            return {"ok": True, "text": json.dumps(body), "usage": {}}

        worker.rpc = fake_rpc
        started = time.monotonic()
        result = await worker.run(
            {
                "task": f"Start at {CONSENT} . Read the flights fixture.",
                "max_steps": 4,
                "vision": False,
            }
        )
        Registry.execute_action = execute
        click_results = [
            e["result"]
            for e in events
            if e["kind"] == "action_result" and "click" in str(e["result"].get("error") or "")
        ]
        observations.update(
            {
                "google_choice": google.choice,
                "ok": result["ok"],
                "final_result": result["final_result"],
                "consent_dismissed": [hit["text"] for hit in result["consent_dismissed"]],
                "consent_events": [e["text"] for e in events if e["kind"] == "consent"],
                "click_error": click_results[0]["error"] if click_results else "",
                "errors": result["errors"],
                "llm_calls": len(calls),
                "seconds": round(time.monotonic() - started, 1),
            }
        )
    finally:
        await worker.close_automation()
    output.write(json.dumps(observations) + "\n")
    output.flush()


asyncio.run(main())
