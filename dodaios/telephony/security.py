"""Security helpers for the telephony bridge (AD-T9).

Two independent checks:

1. **Webhook signature.** Twilio signs every webhook request with the account
   Auth Token. We validate ``X-Twilio-Signature`` against the *public* URL
   Twilio actually reached (not the internal request URL — behind a tunnel /
   reverse proxy the two differ) via ``twilio.request_validator.RequestValidator``.

2. **Per-call WS secret.** The signed ``/voice`` webhook mints a random secret,
   embeds it as a ``<Parameter name="secret">`` in the TwiML ``<Stream>`` (and
   also in the ``wss`` query for redundancy). When the Media Streams socket
   connects, the handler validates the secret against the registry and binds it
   to the ``CallSid``. This stops an attacker who learns the public ``wss`` URL
   from injecting audio without having gone through the signed webhook.

Both checks degrade safely: if the ``twilio`` SDK is not installed,
``validate_twilio_signature`` returns ``False`` (the caller decides whether to
hard-fail or allow in a test/dev context).
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Iterable, Mapping

#: Characters a person may type around the digits of a phone number.
_NUMBER_PUNCTUATION = frozenset("+ -()./")


def normalize_caller(number: str | None) -> str:
    """A phone number as bare E.164 (``+4930123456``), or ``""``.

    ``""`` for anything that is not a plain number: a withheld caller id
    (``anonymous``), a ``client:`` or ``sip:`` address.
    """
    raw = (number or "").strip()
    if not raw or any(not (ch.isdigit() or ch in _NUMBER_PUNCTUATION) for ch in raw):
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("00"):
        digits = digits[2:]
    return f"+{digits}" if digits else ""


def caller_allowed(from_number: str | None, allowed: Iterable[str] | None) -> bool:
    """Whether an inbound call's caller id is on the owner's list.

    An empty list allows nobody. A caller id is asserted by the calling
    network and can be forged by a determined caller, so this keeps strangers
    and robocalls away from the assistant; it is not proof of identity.
    """
    caller = normalize_caller(from_number)
    if not caller:
        return False
    return any(caller == normalize_caller(str(item)) for item in allowed or ())


def generate_call_secret() -> str:
    """Return a URL-safe random secret for one call's Media Streams socket."""
    return secrets.token_urlsafe(24)


def constant_time_equals(a: str, b: str) -> bool:
    """Timing-safe string compare for the per-call WS secret."""
    return hmac.compare_digest(a or "", b or "")


def validate_twilio_signature(
    *,
    auth_token: str | None,
    signature: str | None,
    url: str,
    params: Mapping[str, str],
) -> bool:
    """Validate an ``X-Twilio-Signature`` header.

    Args:
        auth_token: Twilio Auth Token (the signing secret). ``None``/empty ->
            cannot validate -> returns ``False``.
        signature: The ``X-Twilio-Signature`` header value.
        url: The PUBLIC URL Twilio reached (e.g.
            ``https://jarvis.example.com/api/telephony/voice``).
        params: The POST form parameters (``application/x-www-form-urlencoded``).

    Returns:
        ``True`` only when the signature is valid for ``url`` + ``params`` under
        ``auth_token``. ``False`` on any missing input or if the ``twilio`` SDK
        is not importable.
    """
    if not auth_token or not signature or not url:
        return False
    try:
        from twilio.request_validator import (  # type: ignore[import-untyped]
            RequestValidator,
        )
    except ImportError:
        return False
    validator = RequestValidator(auth_token)
    try:
        return bool(validator.validate(url, dict(params), signature))
    except Exception:  # noqa: BLE001 - never let a malformed input raise
        return False


def public_url_for(public_base_url: str, path: str) -> str:
    """Join the configured public base URL with a route path.

    Normalises trailing/leading slashes so the result exactly matches the URL
    Twilio computes its signature over.
    """
    base = (public_base_url or "").rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def public_wss_url(public_base_url: str, path: str) -> str:
    """Return the ``wss://`` URL for the Media Streams socket.

    Converts the ``https`` (or ``http``) scheme of the public base URL to
    ``wss`` (resp. ``ws``) and appends ``path``.
    """
    base = (public_base_url or "").rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


__all__ = [
    "caller_allowed",
    "constant_time_equals",
    "generate_call_secret",
    "normalize_caller",
    "public_url_for",
    "public_wss_url",
    "validate_twilio_signature",
]
