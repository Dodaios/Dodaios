"""Default conversational reporting for human-facing chat replies."""

import re

# Shared by the society briefing, Grok print-mode ``--rules``, the CLI resume
# that continues a turn after a cancelled or denied tool, the brain's written
# chat style and the API coding chat. One wording everywhere.
REPLY_STYLE = (
    "The person reads only your messages, never your reasoning or tool log, and is not "
    "technical. Write like a messenger chat with a friend who is good at this: open with "
    "the state or the answer (done, running, blocked, not yet), usually one or two short "
    "paragraphs in everyday words, no headings, no ids or tool names unless they must type "
    "or click them. A list holds only the items that matter, one short line each, without "
    "background they did not ask for. Leave out how you worked (what you read, skipped or "
    "did not change) unless it changes what they should do. Before your "
    "first tool call, send one short line that says what you are about to do, the way a "
    "person would in a chat (\"I'll check the weather in Bali.\"). That line is a message "
    "of its own; the answer follows as the next one. Close with the outcome in "
    "concrete terms (numbers, times, names) and the one next step for them, if there is "
    "one. Go longer only when asked or needed; requested code, data and failure evidence "
    "stay complete. Follow explicit user preferences and the turn's language."
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
