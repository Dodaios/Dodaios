"""Provider-neutral recovery for function calls emitted as response text.

Some model transports occasionally serialize a function call into the text
stream instead of returning a structured tool-call delta. This module parses
only explicit tool-call envelopes; arbitrary JSON is never treated as an
action. Recovered calls still pass through ToolUseLoop and ToolExecutor.

The envelope does not have to be the whole response. A model that writes
"I'm opening Spotify. {"type":"tool_use",...}" used to execute NOTHING: the
whole-text ``json.loads`` failed, the call was dropped, and the turn ended as
plain text — the maintainer's "nothing happens" (audit GT-13). Envelopes are
now located by balanced-brace scanning, so prose before, after, or on both
sides of the call no longer defeats the recovery.

Widening WHERE we look must not widen WHAT counts as a call. An answer that
merely QUOTES a tool call ("For example, a provider might emit {...}") must
never fire it: a missed recovery costs one answer, a wrongly executed call is
a real side effect. Four gates keep the two apart — see
:func:`extract_leaked_tool_calls`.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

_CALL_MARKERS = ("tool_use", "function_call", "tool_calls", '"function"')
_MISSING = object()

# A fence marker (``` optionally followed by a language tag). Masked out before
# the prose is judged, so a fenced envelope is not mistaken for a quoted one.
_FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*")
# Only a plain or explicitly JSON fence may carry an executable envelope. A
# ```python / ```tool_code block is documentation about a call, not the call.
_ALLOWED_FENCE_TAGS = frozenset({"", "json"})
# Quote characters around an envelope mark it as CITED text, not an action.
_QUOTE_CHARS = ("`", '"', "'", "„", "“", "”", "‚", "‘", "’", "«", "»")

# Prose that DESCRIBES a call instead of performing one. Deliberately broad:
# every marker here costs at most one missed recovery, while a miss in the
# other direction executes something the user never asked for. Covers the
# three product locales plus the vocabulary of an answer *about* tool calls.
_EXAMPLE_MARKER_RE = re.compile(
    r"(?:"
    r"\be\.\s?g\.|\bi\.\s?e\.|\bz\.\s?b\.|\bp\.\s?ej\.|"
    r"\b(?:"
    # EN
    r"example|examples|sample|samples|for instance|such as|pseudo|"
    r"looks?\s+like|would\s+look|might|would|template|schema|format|syntax|"
    r"illustrat\w*|json|tool[\s_-]?use|tool\s+calls?|function\s+calls?|"
    # DE
    r"beispiel\w*|etwa\s+so|so\s+aus|vorlage|schema|format|syntax|"
    r"werkzeugaufruf\w*|"
    # ES
    r"ejemplo\w*|formato|esquema|plantilla|sintaxis"
    r")\b"
    r")",
    re.IGNORECASE,
)
# A leak announces an action in a sentence or two ("Ich öffne Spotify.").
# Paragraphs of prose around an envelope are an explanation that happens to
# contain JSON, so the recovery stands down.
_MAX_SURROUNDING_PROSE_CHARS = 240


def _mask_fences(text: str) -> str:
    """Blank out fence markers, preserving every character offset.

    The masked copy is what the quote and prose gates read: a fenced envelope
    must not look "quoted" just because a fence ends in a backtick.
    """
    return _FENCE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _fence_tags(text: str) -> list[str]:
    return [match.group(0).lstrip("`").lower() for match in _FENCE_RE.finditer(text)]


def _json_spans(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` of every balanced top-level JSON object/array.

    Brace counting, not a parser: string literals and backslash escapes are
    tracked so a ``}`` inside a JSON string never closes a span. An opener
    that is never closed (a truncated payload) yields no span at all.
    """
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if depth == 0:
            if char in "{[":
                depth = 1
                start = index
                in_string = False
                escaped = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                spans.append((start, index + 1))
    return spans


def _is_quoted(masked: str, start: int, end: int) -> bool:
    """True when the span sits inside quotation marks or an inline code span."""
    before = masked[:start].rstrip()
    after = masked[end:].lstrip()
    return before.endswith(_QUOTE_CHARS) or after.startswith(_QUOTE_CHARS)


def _surrounding_prose(masked: str, spans: list[tuple[int, int]]) -> str:
    """Everything outside the executed envelopes, whitespace-collapsed."""
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(masked[cursor:start])
        cursor = end
    parts.append(masked[cursor:])
    return " ".join("".join(parts).split())


def _decode_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            # Silence is the decision: arguments we cannot decode mean we do
            # not know what the call would do, so the envelope is refused
            # rather than guessed at. The caller sees "no call found".
            return None
        return dict(decoded) if isinstance(decoded, dict) else None
    return None


def _normalize_call(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None

    call: Any = block
    if isinstance(block.get("function_call"), dict):
        call = block["function_call"]
    elif isinstance(block.get("function"), dict):
        call = block["function"]

    if not isinstance(call, dict):
        return None
    call_type = str(block.get("type") or call.get("type") or "")
    explicitly_wrapped = (
        call is not block
        or call_type in {"tool_use", "function_call", "function"}
    )
    if not explicitly_wrapped:
        return None

    name = call.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    arguments = call.get("input", _MISSING)
    if arguments is _MISSING:
        arguments = call.get("arguments", call.get("args", _MISSING))
    decoded_arguments = (
        {} if arguments is _MISSING else _decode_arguments(arguments)
    )
    if decoded_arguments is None:
        return None
    fingerprint = json.dumps(
        [name.strip(), decoded_arguments],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return {
        "id": str(
            block.get("id")
            or call.get("id")
            or f"leaked_{sha256(fingerprint).hexdigest()[:12]}"
        ),
        "name": name.strip(),
        "input": decoded_arguments,
    }


def _calls_from_candidate(candidate: Any) -> list[dict[str, Any]]:
    blocks = candidate if isinstance(candidate, list) else [candidate]
    calls: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("tool_calls"), list):
            for nested in block["tool_calls"]:
                normalized = _normalize_call(nested)
                if normalized is not None:
                    calls.append(normalized)
            continue
        normalized = _normalize_call(block)
        if normalized is not None:
            calls.append(normalized)
    return calls


def _call_identity(call: dict[str, Any]) -> str:
    """Name + arguments — the same action, however the provider labelled it."""
    return json.dumps(
        [call["name"], call["input"]],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def extract_leaked_tool_calls(text: str, tools: Any = None) -> list[dict[str, Any]]:
    """Parse explicit text-serialized tool calls into normal loop call records.

    With ``tools`` (the tools offered this round), chat-template markup —
    Qwen/Hermes ``<tool_call>{...}</tool_call>`` and Mistral ``[TOOL_CALLS]`` —
    is recovered first, limited to offered tool names (see
    :func:`extract_tagged_tool_calls`). Without ``tools`` only the explicit
    JSON envelopes below count, since a bare ``{"name": ...}`` cannot be told
    from a quoted sample unless its name is known to be real.

    An envelope may sit anywhere in the response — alone, after prose, before
    prose, between two sentences, or inside a ```json fence. Every envelope
    found in the text is returned, in document order, with identical calls
    collapsed to one.

    Four gates separate an intended call from a quoted sample. All of them
    fail closed, i.e. they return ``[]`` for the WHOLE text rather than
    executing a subset:

    1. Shape — unchanged: only an explicit ``tool_use`` / ``function_call`` /
       ``function`` envelope with a non-empty name and object arguments.
    2. Fences — an unbalanced ``` count means a truncated payload, and a
       language tag other than ``json`` means documentation about a call.
    3. Quoting — an envelope wrapped in quotation marks or inline backticks is
       being cited, not invoked.
    4. Prose — the text outside the envelopes must be short and free of
       example vocabulary ("for example", "z. B.", "schema", "json", …).
    """
    if tools and text and has_tool_markup(text):
        tagged, _remaining = extract_tagged_tool_calls(text, tools)
        if tagged:
            return tagged
    if not text or not any(marker in text.lower() for marker in _CALL_MARKERS):
        return []

    masked = _mask_fences(text)
    tags = _fence_tags(text)
    if len(tags) % 2 or any(tag not in _ALLOWED_FENCE_TAGS for tag in tags):
        return []

    calls: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []
    for start, end in _json_spans(masked):
        try:
            candidate = json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            # Expected on ordinary prose: balanced braces are not proof of
            # JSON (a smiley, a Python repr with single quotes). Nothing to
            # report — this span is simply not an envelope.
            continue
        found = _calls_from_candidate(candidate)
        if not found:
            continue
        if _is_quoted(masked, start, end):
            return []
        calls.extend(found)
        consumed.append((start, end))

    if not calls:
        return []

    prose = _surrounding_prose(masked, consumed)
    if len(prose) > _MAX_SURROUNDING_PROSE_CHARS:
        return []
    if _EXAMPLE_MARKER_RE.search(prose):
        return []

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in calls:
        identity = _call_identity(call)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(call)
    return unique


# ---------------------------------------------------------------------------
# Chat-template tool markup (Qwen / Hermes ``<tool_call>``, Mistral
# ``[TOOL_CALLS]``).
#
# A local server that does not parse tool calls (llama.cpp without
# ``--jinja``, LM Studio with an unknown template, an Ollama model whose
# template lacks a tool parser) hands the model's raw markup back as text. The
# markup is a template token, not prose, so it is a far stronger signal than a
# bare JSON envelope — but it carries no ``type`` wrapper, so the gates are
# different: the call must name a tool that was actually OFFERED this round,
# and markup inside a code fence is documentation, never a call.
# ---------------------------------------------------------------------------

TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"
MISTRAL_TOOL_CALLS = "[TOOL_CALLS]"
_MISTRAL_ARGS = "[ARGS]"

_TAGGED_BLOCK_RE = re.compile(
    r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.DOTALL | re.IGNORECASE
)
# Qwen3-Coder's XML flavour: <function=name><parameter=key>value</parameter></function>
_XML_FUNCTION_RE = re.compile(
    r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.DOTALL
)
_XML_PARAMETER_RE = re.compile(
    r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", re.DOTALL
)
_MISTRAL_NAME_RE = re.compile(r"\s*([A-Za-z0-9_.\-/]+)\s*\[ARGS\]")


def has_tool_markup(text: str) -> bool:
    """Whether ``text`` contains a chat-template tool-call marker."""
    lowered = (text or "").lower()
    return TOOL_CALL_OPEN in lowered or MISTRAL_TOOL_CALLS.lower() in lowered


def _offered(tools: Any) -> dict[str, dict[str, Any] | None]:
    """``{name: input_schema}`` from schemas, a mapping, or plain names."""
    offered: dict[str, dict[str, Any] | None] = {}
    if not tools:
        return offered
    if isinstance(tools, dict):
        return {str(k): (v if isinstance(v, dict) else None) for k, v in tools.items()}
    for tool in tools:
        if isinstance(tool, str):
            offered[tool] = None
        elif isinstance(tool, dict):
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = fn.get("name")
            if isinstance(name, str) and name:
                schema = fn.get("input_schema", fn.get("parameters"))
                offered[name] = schema if isinstance(schema, dict) else None
    return offered


def _bare_call(block: Any, offered: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    """``{"name": ..., "arguments": ...}`` (or a wrapped form) → call record."""
    if not isinstance(block, dict):
        return None
    call = block
    for key in ("function", "function_call"):
        if isinstance(block.get(key), dict):
            call = block[key]
            break
    name = call.get("name")
    if not isinstance(name, str) or name.strip() not in offered:
        return None
    arguments = _MISSING
    for key in ("arguments", "parameters", "input", "args"):
        if key in call:
            arguments = call[key]
            break
    decoded = {} if arguments is _MISSING else _decode_arguments(arguments)
    if decoded is None:
        return None
    return _record(name.strip(), decoded, block.get("id") or call.get("id"))


def _record(name: str, arguments: dict[str, Any], call_id: Any = None) -> dict[str, Any]:
    fingerprint = json.dumps(
        [name, arguments], sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return {
        "id": str(call_id or f"leaked_{sha256(fingerprint).hexdigest()[:12]}"),
        "name": name,
        "input": arguments,
    }


def _xml_value(raw: str, schema: dict[str, Any] | None, key: str) -> Any:
    """A Qwen3-Coder parameter value, typed by the tool's schema when known."""
    value = raw.strip("\n")
    declared = None
    if schema and isinstance(schema.get("properties"), dict):
        prop = schema["properties"].get(key)
        if isinstance(prop, dict):
            declared = prop.get("type")
    if declared == "string":
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        # Not JSON: the value is plain text, which is what the template
        # writes for every string argument.
        return value


def _calls_in_payload(
    payload: str, offered: dict[str, dict[str, Any] | None]
) -> tuple[list[dict[str, Any]], bool]:
    """Calls inside one ``<tool_call>`` body, and whether it was call-shaped.

    Call-shaped means the body WAS an attempted call (JSON with a ``name``, or
    a ``<function=…>`` block) even when the name is not offered — the caller
    hides such markup instead of showing it as an answer.
    """
    body = payload.strip()
    xml = list(_XML_FUNCTION_RE.finditer(body))
    if xml:
        calls = []
        for match in xml:
            name = match.group(1).strip()
            if name not in offered:
                continue
            schema = offered[name]
            arguments = {
                p.group(1).strip(): _xml_value(p.group(2), schema, p.group(1).strip())
                for p in _XML_PARAMETER_RE.finditer(match.group(2))
            }
            calls.append(_record(name, arguments))
        return calls, True
    calls = []
    shaped = False
    for start, end in _json_spans(body):
        try:
            candidate = json.loads(body[start:end])
        except (json.JSONDecodeError, ValueError):
            # Not JSON at all: not a call, the caller keeps the text.
            continue
        blocks = candidate if isinstance(candidate, list) else [candidate]
        for block in blocks:
            if isinstance(block, dict) and (
                "name" in block or "function" in block or "function_call" in block
            ):
                shaped = True
            call = _bare_call(block, offered)
            if call is not None:
                calls.append(call)
    return calls, shaped


def _mistral_calls(
    tail: str, offered: dict[str, dict[str, Any] | None]
) -> tuple[list[dict[str, Any]], int]:
    """Calls right after a ``[TOOL_CALLS]`` marker, and how much text they used."""
    stripped = tail.lstrip()
    lead = len(tail) - len(stripped)
    if stripped[:1] in ("[", "{"):
        spans = _json_spans(stripped)
        if not spans or spans[0][0] != 0:
            return [], 0
        end = spans[0][1]
        try:
            candidate = json.loads(stripped[:end])
        except (json.JSONDecodeError, ValueError):
            # A truncated or malformed array executes nothing.
            return [], 0
        blocks = candidate if isinstance(candidate, list) else [candidate]
        calls = [c for c in (_bare_call(b, offered) for b in blocks) if c is not None]
        return calls, lead + end
    # v11+ tokenizer: ``name[ARGS]{...}``
    match = _MISTRAL_NAME_RE.match(tail)
    if not match:
        return [], 0
    rest = tail[match.end():]
    spans = _json_spans(rest)
    if not spans or rest[: spans[0][0]].strip():
        return [], 0
    try:
        arguments = json.loads(rest[spans[0][0]: spans[0][1]])
    except (json.JSONDecodeError, ValueError):
        # Malformed arguments: refuse rather than guess.
        return [], 0
    name = match.group(1)
    if name not in offered or not isinstance(arguments, dict):
        return [], match.end() + spans[0][1]
    return [_record(name, arguments)], match.end() + spans[0][1]


def _fenced(text: str, index: int) -> bool:
    """Whether ``index`` sits inside a ``` code fence."""
    return text.count("```", 0, index) % 2 == 1


def extract_tagged_tool_calls(
    text: str, tools: Any
) -> tuple[list[dict[str, Any]], str]:
    """Recover chat-template tool markup; return ``(calls, remaining_text)``.

    ``tools`` are the tools OFFERED this round (schemas, ``{name: schema}``, or
    names). Only calls naming one of them are returned. Call-shaped markup is
    removed from the remaining text whether or not it named an offered tool —
    it is never an answer a person should see or hear. Markup inside a code
    fence, and markup whose body is not a call at all, stay as text.
    """
    if not text or not has_tool_markup(text):
        return [], text
    offered = _offered(tools)
    calls: list[dict[str, Any]] = []
    pieces: list[str] = []
    cursor = 0
    for match in _TAGGED_BLOCK_RE.finditer(text):
        if _fenced(text, match.start()):
            continue
        found, shaped = _calls_in_payload(match.group(1), offered)
        if not shaped:
            continue
        calls.extend(found)
        pieces.append(text[cursor: match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    remaining = "".join(pieces)

    marker = remaining.upper().find(MISTRAL_TOOL_CALLS)
    while marker != -1 and not _fenced(remaining, marker):
        tail = remaining[marker + len(MISTRAL_TOOL_CALLS):]
        found, used = _mistral_calls(tail, offered)
        if not used:
            break
        calls.extend(found)
        remaining = remaining[:marker] + tail[used:]
        marker = remaining.upper().find(MISTRAL_TOOL_CALLS)

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in calls:
        identity = _call_identity(call)
        if identity not in seen:
            seen.add(identity)
            unique.append(call)
    return unique, (remaining.strip() if remaining != text else text)


__all__ = [
    "MISTRAL_TOOL_CALLS",
    "TOOL_CALL_CLOSE",
    "TOOL_CALL_OPEN",
    "extract_leaked_tool_calls",
    "extract_tagged_tool_calls",
    "has_tool_markup",
]
