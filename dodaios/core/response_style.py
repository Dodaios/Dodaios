"""Default conversational reporting for human-facing chat replies."""

import re

# Shared by the society briefing, Grok print-mode ``--rules``, the CLI resume
# that continues a turn after a cancelled or denied tool, the brain's written
# chat style and the API coding chat. One wording everywhere.
#
# The one length rule of a written reply lives here, as a number the model can
# hold itself to. Rules elsewhere (the persona's reporting line, the lead
# doctrine, the initiative section, the follow-up turns) say WHAT goes into a
# reply and defer to this for HOW LONG it is. A reply used to collect a
# paragraph from each of them (maintainer, 2026-11-13: "no normal person writes
# a 5,000-character chat reply").
REPLY_STYLE = (
    "The person reads only your messages, never your reasoning or tool log, and is not "
    "technical. Write like a messenger chat with a friend who is good at this: short, "
    "plain, direct. A reply is two to four short sentences, at most about 500 characters, "
    "or a few one-line bullets when they must see several separate things. Open with the "
    "answer or the state (done, running, blocked, not yet), with concrete numbers, times "
    "and names. No headings, no bold labels, no ids or tool names unless they must type "
    "or click them. Leave out background they did not ask for, how you worked, caveats "
    "that change nothing for them, and anything you already told them. If something "
    "failed or they must act, one sentence says it. Before your first tool call, send one "
    "short line that says what you are about to do, the way a person would in a chat "
    "(\"I'll check the weather in Bali.\"), as a message of its own; the answer follows "
    "as the next one. Go longer only when they ask for detail or for something long by "
    "nature (code, a text, data, a list they want); that stays complete. Follow explicit "
    "user preferences and the turn's language."
)
# Kept names: fresh and resumed prompts, the brain's written style and the dedupe in
# BrainManager._build_system_prompt all reference these.
CONVERSATIONAL_TURN_REMINDER = REPLY_STYLE
CONVERSATIONAL_RESPONSE_STYLE = REPLY_STYLE

#: The fence language of a chart block in a written reply. The chat draws the
#: block instead of showing it (``CHART_FENCE`` in
#: ``dodaios/ui/web/frontend/src/lib/chartSpec.ts``, which also reads the
#: fields named below); a parity test keeps both names equal.
CHART_FENCE = "chart"

#: When and how the assistant adds a small chart to a written answer. Part of
#: the assistant's own chat prompt on both seats (the CLI seat's preamble and
#: the brain's written style). A surface that cannot draw gets the reply
#: through :func:`without_charts`.
CHART_GUIDANCE = (
    f"Charts: the chat draws a fenced code block with the language `{CHART_FENCE}` as a "
    "small chart. Add one, after the sentence that states the result, when a written "
    "answer rests on a series of numbers: a price or rate over time (for a share, a "
    "currency or a coin, its recent course when a tool gives it to you), a forecast, "
    "amounts compared across several things. The block holds one JSON object, for example "
    '{"type": "line", "title": "ACME share price", "unit": "USD", "note": "daily close, '
    '1 to 3 June", "value": "142.30 USD", "delta": "+2.1 % in 3 days", "x": ["1 Jun", '
    '"2 Jun", "3 Jun"], "series": [{"name": "ACME", "data": [139.4, 140.1, 142.3]}]}. '
    "type is line or area for a trend over time, column for amounts per period, bar for "
    "comparing named things. x and every data list have the same length, null marks a "
    "missing value; at most 6 series, all in one unit; note, value and delta are optional. "
    "Every number comes from a tool result or from the person, never from memory or an "
    "estimate. No chart for a single number or fewer than three points, and none in a "
    "reply that is spoken or goes to a phone chat. The text must make sense without the "
    "chart."
)

#: How the assistant writes a web link in a written answer. The chat draws a
#: Markdown link to a web page as the website's logo and the link's words, with
#: the full address on a hover card (``WebLink.tsx`` in the chat frontend); a
#: bare address is shortened there too, but the assistant's own words read
#: better than any shortening. Part of the assistant's own chat prompt on both
#: seats, next to :data:`CHART_GUIDANCE`.
LINK_GUIDANCE = (
    "Links: write every web link as a Markdown link whose text is a short name of one to "
    "five words saying what it is, never the bare address and never the address as the "
    "link text: [Post](https://x.com/someone/status/123), [Dodaios repo]"
    "(https://github.com/Dodaios/Dodaios), [Local-first open source alternative]"
    "(https://www.reddit.com/r/LocalLLaMA/comments/abc/...), [Show HN thread]"
    "(https://news.ycombinator.com/item?id=123). The chat draws the website's logo in front "
    "of the name and shows the full address when the person points at it, so do not add "
    "the site's name, the domain or the address next to the link. Copy the address exactly "
    "as a tool gave it to you; never invent or shorten one. Link what you did or found "
    "whenever it has a page, so the person can check it with one click: the email you "
    "sent ([sent email](...)), the event you created, the file you saved or shared, and "
    "each pull request, issue, commit, post or article you name, one link per item. Take "
    "the address from the tool result (a `url` field) or ask the tool for it (GitHub: "
    "`gh pr list --json number,title,url`, `gh pr view <n> --json url`)."
)

_CHART_BLOCK_RE = re.compile(
    r"[ \t]*```[ \t]*" + re.escape(CHART_FENCE) + r"[ \t]*\r?\n.*?(?:```[ \t]*|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def without_charts(text: str) -> str:
    """``text`` for a surface that cannot draw: its chart blocks removed.

    A chart block is JSON; on a phone chat or in a notification it would be a
    wall of brackets. The reply is written to stand without the chart, so the
    block is dropped, also one that was cut off before its closing fence.
    """
    if CHART_FENCE not in (text or ""):
        return text or ""
    return re.sub(r"\n{3,}", "\n\n", _CHART_BLOCK_RE.sub("", text)).strip()


TASK_EXECUTION_GUIDANCE = (
    "A clear request authorizes the work within your current permissions: do all of it "
    "now and decide optional details yourself. Call something done only when a tool "
    "result in this conversation shows it; otherwise say exactly what is pending or blocked."
)

AGENT_QUESTION_GUIDANCE = (
    "A question only the person can answer goes through society_ask_user, never only into "
    "your reply."
)

KEEP_GOING_ON_TOOL_FAILURE = (
    "A failed, cancelled or denied tool call does not end the task: continue on another "
    "permitted path, and never work around a denial."
)

#: Society agents: a service the task needs is offered as a Connect card in the
#: chat (dodaios/society/connect_tool.py), not as a walk to the Plugins page.
CONNECT_GUIDANCE = (
    "When a task needs one of them, call society_request_connect(kind='plugin', id=...) "
    "before anything else: it puts a Connect card with the service's logo in the chat. Do "
    "not send the person to the Plugins page and do not answer that you cannot do it."
)

#: Society agents: the one way a secret reaches an agent (dodaios/society/credential_tool.py).
CREDENTIAL_GUIDANCE = (
    "Secrets reach you only through society_request_credential, as environment variables "
    "in society_shell, and website logins only through society_request_login, as browser "
    "placeholders; never ask for, show or store one anywhere else."
)
