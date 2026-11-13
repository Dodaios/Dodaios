"""Cookie banners and consent walls, answered with the most private choice.

A consent wall (Google's ``consent.google.com``, OneTrust, Usercentrics,
Didomi, Cookiebot, Sourcepoint and other TCF banners) stands between the
browser agent and the page it was sent to. Letting the model click it costs
whole steps, and every model click on a page is an ``ask`` action that waits
for the person's approval. So the worker answers these walls itself, before
each agent step, with "reject all" or "only necessary cookies". It never
accepts: a banner that offers no refusal is left for the agent.

This module runs inside the isolated browser runtime (``live_runner.py``
imports it as a sibling file), so it must not import anything from Dodaios.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

# Button labels, compared after lowercasing and folding punctuation to spaces.
# German and English, the languages Dodaios ships. Ranks (lower wins):
# 0 "reject all", 1 "only necessary cookies", 2 "continue without consent",
# 3 a plain "reject" inside a consent banner. Kept as written: each German
# line carries the marker of the no-new-German gate (scripts/ci).
# fmt: off
WORDS: dict[str, Any] = {
    "strong": [
        "alle ablehnen", "alles ablehnen", "alle cookies ablehnen",  # i18n-allow: button labels
        "alle optionalen ablehnen", "optionale cookies ablehnen",  # i18n-allow: button labels
        "alle optionalen cookies ablehnen",  # i18n-allow: button label
        "reject all", "reject all cookies", "reject optional cookies",
        "reject non-essential cookies", "reject non essential cookies",
        "decline all", "decline all cookies", "decline optional cookies",
        "deny all", "refuse all", "refuse all cookies",
    ],
    "necessary": [
        r"\b(nur|only)\b.{0,30}\b(notwendig|erforderlich|essenziell|essentiell"  # i18n-allow
        r"|necessary|essential|required)",
        r"\b(notwendig|erforderlich|essenziell|essentiell"  # i18n-allow: label pattern
        r"|necessary|essential|required)\w*\b.{0,20}\b(nur|only)\b",
    ],
    "without": [
        "weiter ohne einwilligung", "ohne einwilligung fortfahren",  # i18n-allow: button labels
        "ohne einwilligung weiter", "weiter ohne zustimmung",  # i18n-allow: button labels
        "ohne zustimmung fortfahren", "ohne zustimmung weiter",  # i18n-allow: button labels
        "fortfahren ohne zu akzeptieren", "weiter ohne zu akzeptieren",  # i18n-allow: labels
        "nicht einwilligen",  # i18n-allow: button label
        "continue without accepting", "continue without agreeing", "continue without consent",
        "do not consent", "i do not accept", "i do not agree", "do not accept",
    ],
    "plain": [
        "ablehnen", "nicht zustimmen", "nicht einverstanden", "verweigern",  # i18n-allow: labels
        "reject", "decline", "deny", "refuse", "disagree", "i disagree",
    ],
    # An accepting label never counts, unless it also says "not" or "without".
    "accept": "akzept|zustimm|accept|agree|allow|erlaub|einverstanden",  # i18n-allow: pattern
    "negation": "nicht|not|without|ohne|ablehnen|reject|decline",  # i18n-allow: pattern
    # "Refuse and subscribe", "Pur-Abo": a pay-or-consent wall's refusal is a sale.
    "paywall": (
        r"abonn|\babo\b|\bpur\b|subscri|kaufen|\bbuy\b|bezahl|\bpay\b"  # i18n-allow
        r"|anmelden|log ?in|sign ?in|registrier|register"  # i18n-allow: label pattern
    ),
    # Marks of a consent banner container (ids, classes, labels).
    "context": (
        "cookie|consent|gdpr|dsgvo|privacy|datenschutz|einwilligung"  # i18n-allow: markers
        "|cmpbox|cmpwrapper|cmp-container|didomi|onetrust|usercentrics|sp_message|truste"
        "|cybot|qc-cmp|borlabs|klaro|cky-|cmplz|iubenda|osano|tcf"
    ),
    # A banner talks about cookies or tracking; a sign-in "consent" screen does not.
    "topic": "cookie|tracking|werbe|advertis|partner|tcf|personalisiert|personalized|personalised",
    # Whole pages that are a consent wall (Google's redirect target and CMP frames).
    "consent_host": (
        r"^(consent\.(google|youtube)\.[a-z.]+|consent\.yahoo\.com|guce\.[a-z.]+"
        r"|[a-z0-9.-]*privacy-mgmt\.com|[a-z0-9.-]*consentmanager\.net"
        r"|[a-z0-9.-]*cookielaw\.org|[a-z0-9.-]*usercentrics\.eu)$"
    ),
    # Refusal controls of known CMPs, tried before any label.
    "known": [
        "#onetrust-reject-all-handler",
        ".ot-pc-refuse-all-handler",
        "#CybotCookiebotDialogBodyButtonDecline",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
        "[data-testid='uc-deny-all-button']",
        "#didomi-notice-disagree-button",
        ".didomi-continue-without-agreeing",
        "button.sp_choice_type_13",
        "button.sp_choice_type_REJECT_ALL",
        ".fc-cta-do-not-consent",
        ".cky-btn-reject",
        ".cmplz-deny",
        ".osano-cm-denyAll",
        ".iubenda-cs-reject-btn",
        "#truste-consent-required",
        "a._brlbs-refuse-btn",
        "#cmpbntnotxt",
        ".cmpboxbtnno",
    ],
}
# fmt: on

# One frame's look for a refusal button. Returns what it clicked, or null.
# Rank -1 is a known CMP's refusal control.
DISMISS_SCRIPT = r"""
(words) => {
  const KNOWN = words.known;
  const STRONG = words.strong;
  const NECESSARY = words.necessary.map((source) => new RegExp(source));
  const WITHOUT = words.without;
  const PLAIN = words.plain;
  const ACCEPT = new RegExp(words.accept);
  const NEGATION = new RegExp(words.negation);
  const PAYWALL = new RegExp(words.paywall);
  const CONTEXT = new RegExp(words.context, "i");
  const TOPIC = new RegExp(words.topic, "i");
  const CONSENT_HOST = new RegExp(words.consent_host, "i");
  const CLICKED = "data-dodaios-consent-clicked";
  const norm = (text) => String(text || "")
    .toLowerCase()
    .replace(/[«»›‹>→"'“”„.:!]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const label = (el) => norm(
    el.innerText || el.textContent || el.value || el.getAttribute("aria-label") || el.title || ""
  );
  const rank = (text) => {
    if (!text || text.length > 70 || PAYWALL.test(text)) return null;
    if (STRONG.some((p) => text === p || text.startsWith(p + " "))) return 0;
    if (NECESSARY.some((r) => r.test(text))) return 1;
    if (WITHOUT.some((p) => text.includes(p))) return 2;
    if (ACCEPT.test(text) && !NEGATION.test(text)) return null;
    const plain = (p) => text === p || text.startsWith(p + " ") || text.endsWith(" " + p);
    if (PLAIN.some(plain)) return 3;
    return null;
  };
  const parentOf = (el) => el.parentElement || (el.getRootNode && el.getRootNode().host) || null;
  const visible = (el) => {
    if (!el.isConnected) return false;
    const box = el.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) return false;
    for (let node = el; node && node.nodeType === 1; node = parentOf(node)) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return false;
      }
    }
    return true;
  };
  const host = location.hostname || "";
  const framed = window !== window.top;
  const bodyText = () => (document.body && document.body.innerText) || "";
  const pageTopic = () => TOPIC.test(bodyText().slice(0, 4000));
  const consentPage = CONSENT_HOST.test(host);
  let framedTopic = null;
  const inConsentContext = (el) => {
    if (consentPage) return true;
    for (let node = parentOf(el), depth = 0; node && depth < 40; node = parentOf(node), depth++) {
      if (node.nodeType !== 1) continue;
      const marks = [node.id, typeof node.className === "string" ? node.className : "",
        node.getAttribute("aria-label"), node.getAttribute("data-testid")].join(" ");
      const role = node.getAttribute("role");
      const banner = CONTEXT.test(marks) || role === "dialog" || role === "alertdialog"
        || node.getAttribute("aria-modal") === "true" || node.tagName === "DIALOG";
      const text = banner ? (node.innerText || node.textContent || "") : "";
      if (banner && TOPIC.test(text.slice(0, 4000))) return true;
    }
    if (framed) {
      if (framedTopic === null) framedTopic = pageTopic();
      return framedTopic;
    }
    return false;
  };
  const roots = [];
  const walk = (root) => {
    roots.push(root);
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  let best = null;
  for (const root of roots) {
    for (const selector of KNOWN) {
      for (const el of root.querySelectorAll(selector)) {
        if (!el.hasAttribute(CLICKED) && !PAYWALL.test(label(el)) && visible(el)) {
          best = { el, rank: -1, how: selector };
          break;
        }
      }
      if (best) break;
    }
    if (best) break;
  }
  if (!best) {
    const clickable = "button, [role='button'], a, input[type='submit'], input[type='button']";
    for (const root of roots) {
      for (const el of root.querySelectorAll(clickable)) {
        if (el.hasAttribute(CLICKED)) continue;
        const r = rank(label(el));
        if (r === null || (best && best.rank <= r)) continue;
        if (!visible(el) || !inConsentContext(el)) continue;
        best = { el, rank: r, how: "text" };
        if (r === 0) break;
      }
      if (best && best.rank === 0) break;
    }
  }
  if (!best) return null;
  const text = label(best.el).slice(0, 80);
  // A banner that animates out keeps its button for a moment; never click it twice.
  best.el.setAttribute(CLICKED, "1");
  best.el.click();
  return { text, rank: best.rank, how: best.how, host, framed };
}
"""

# A wall is answered in at most this many clicks (a two-stage banner, or a
# Google consent page followed by an in-page banner on the destination).
_MAX_ROUNDS = 3
# One frame's search; a frame that is navigating away answers nothing.
_FRAME_TIMEOUT_S = 2.0
# The page that loads after a click (Google's consent form posts and redirects).
_SETTLE_TIMEOUT_MS = 5000


async def dismiss_consent(page: Any, *, budget_s: float = 8.0) -> list[dict[str, Any]]:
    """Refuse every cookie or consent wall on ``page``; return what was clicked.

    Bounded by ``budget_s`` in total. Never raises: a page this cannot read is
    left to the agent exactly as before.
    """
    dismissed: list[dict[str, Any]] = []
    if page is None:
        return dismissed
    try:
        async with asyncio.timeout(budget_s):
            for _ in range(_MAX_ROUNDS):
                if page.is_closed():
                    break
                hit = await _dismiss_once(page)
                if hit is None:
                    break
                dismissed.append(hit)
                await _settle(page)
    except TimeoutError:
        log.debug("Consent check stopped at its time budget")
    except Exception:
        # The agent still sees the page and can answer the banner itself.
        log.debug("Consent check failed", exc_info=True)
    return dismissed


async def _dismiss_once(page: Any) -> dict[str, Any] | None:
    main = page.main_frame
    frames = [main, *(frame for frame in page.frames if frame is not main)]
    for frame in frames:
        if frame.is_detached():
            continue
        try:
            hit = await asyncio.wait_for(frame.evaluate(DISMISS_SCRIPT, WORDS), _FRAME_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — a detached, navigating or blocked frame has no banner
            log.debug("Frame %s not checked for a consent wall", frame.url, exc_info=True)
            continue
        if hit:
            return {**hit, "url": frame.url}
    return None


async def _settle(page: Any) -> None:
    """Give a click's navigation or banner animation a moment to finish."""
    await asyncio.sleep(0.4)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=_SETTLE_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — a page still loading is checked again before the next step
        log.debug("Page after the consent click is still loading", exc_info=True)
