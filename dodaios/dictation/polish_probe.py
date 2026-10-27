"""Does this wording provider actually work — here, on this host, right now?

The provider cards answer "ready" as soon as a key STRING is stored. For the
wording pass that claim is weaker than anywhere else in the app, because the
pass is INVISIBLE when it fails: it delivers the raw transcript and says
nothing. An out-of-credits account, a model the local server never pulled, a
family whose answer arrives after the latency budget — all three look exactly
like a healthy provider on the card, and all three mean the user's dictation is
never tidied up. Measured on one real install, four of five cards that read
"ready" could not format a sentence.

So this module asks the provider itself, with the same client the real pass
uses, and returns the shared ``ProviderTestResult`` vocabulary so the card, the
tab dot and the CLI all speak one language.

**Why it lives in the dictation layer.** ``dodaios/brain/provider_test.py`` owns
the per-tier probes for every other card, and this one may not live there: no
module under ``dodaios/brain/`` may name the wording pass, because a call site
there would put a model call one import away from the spoken hot path (AP-11,
guarded by ``tests/unit/dictation/test_polish_boot_safety.py``). The status
vocabulary and the error classifier are imported FROM that module rather than
restated, so the two can never drift (BUG-008 class).

Every import here is deferred to call time — the probe must never appear on a
boot path (AP-26).
"""
from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

log = logging.getLogger(__name__)

#: The one-line sample the probe sends. Deliberately tiny and deterministic: it
#: costs a fraction of a cent, and what is measured is whether the family
#: answers within the user's budget — not how well it writes. Lower-cased and
#: unpunctuated so a working model has something to do.
PROBE_SYSTEM = (
    "Rewrite the user's text with correct capitalization and punctuation. "
    "Change no words. Answer with the rewritten text only."
)
PROBE_USER = "we can ship it on tuesday"

#: Default budget when the config carries none, mirroring ``DictationConfig``.
_DEFAULT_BUDGET_MS = 1200.0

#: How far above the user's budget the probe still waits. It exists to tell
#: "answers late" apart from "never answers": both fail the budget, but only one
#: of them is worth the sentence "raise the limit or pick a faster provider".
_CEILING_FACTOR = 4.0
_CEILING_FLOOR_S = 8.0


def _default_make_client(family: Any, model: str) -> Any:
    from dodaios.dictation.polish_client import build_polish_client

    return build_polish_client(family, model=model)


def _resolve_probe_model(family: Any, dictation_cfg: Any, model: str) -> str:
    """The model the real pass would use for *family*; its default on trouble.

    Reads the TRANSLATE switch, because with it on the pass runs on the
    family's translation tier and that is a different model — often a larger
    one, and one the account may not be entitled to. A probe that dialled the
    formatter's model instead would answer "ready" for a setup whose very next
    dictation 404s, which is the exact claim this module exists to stop the
    provider cards from making.
    """
    if model:
        return model
    try:
        from dodaios.dictation.polish import resolve_translate_target
        from dodaios.dictation.polish_client import resolve_model

        return resolve_model(
            family,
            dictation_cfg,
            primary_id=getattr(family, "id", ""),
            translating=bool(resolve_translate_target(dictation_cfg)),
        )
    except Exception as exc:  # noqa: BLE001 — a resolver hiccup is not a verdict
        log.debug("polish probe model resolution failed (%s); using the default.", exc)
        return str(getattr(family, "default_model", "") or "")


#: How long the Ollama state lookup may take. It is a local HTTP GET, so a
#: server that needs longer than this is the answer in itself.
_OLLAMA_STATE_TIMEOUT_S = 3.0


async def _default_ollama_state(family: Any) -> dict[str, Any]:
    """What the user's Ollama server holds: ``{"root", "reachable", "installed", "loaded"}``.

    ``installed`` comes from ``/api/tags`` and ``loaded`` from ``/api/ps``.
    ``reachable`` is False when ``/api/tags`` does not answer. ``loaded`` is
    None when ``/api/ps`` alone failed, which means "unknown", not "empty".
    """
    import httpx

    from dodaios.plugins.brain.ollama import normalize_server_root

    root = normalize_server_root(str(getattr(family, "effective_base_url", "") or ""))
    state: dict[str, Any] = {"root": root, "reachable": False, "installed": (), "loaded": None}
    async with httpx.AsyncClient(timeout=_OLLAMA_STATE_TIMEOUT_S) as client:
        try:
            resp = await client.get(f"{root}/api/tags")
            resp.raise_for_status()
            rows = (resp.json() or {}).get("models") or []
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.debug("polish probe: Ollama /api/tags at %s failed (%s)", root, exc)
            return state
        state["reachable"] = True
        state["installed"] = tuple(
            str(r.get("name") or "") for r in rows if isinstance(r, dict) and r.get("name")
        )
        try:
            resp = await client.get(f"{root}/api/ps")
            resp.raise_for_status()
            rows = (resp.json() or {}).get("models") or []
            state["loaded"] = tuple(
                str(r.get("name") or "") for r in rows if isinstance(r, dict) and r.get("name")
            )
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.debug("polish probe: Ollama /api/ps at %s failed (%s)", root, exc)
    return state


def _has_model(names: Any, model: str) -> bool:
    from dodaios.brain.ollama_inventory import same_model

    return any(same_model(str(n), model) for n in (names or ()))


def _missing_model_sentence(model: str, installed: Any) -> str:
    """The fix for a wording model the local server never pulled."""
    sentence = (
        f"The model '{model}' is not installed in Ollama. Run `ollama pull {model}`, "
        "or pick an installed model as the dictation wording model"
    )
    from dodaios.brain.ollama_inventory import is_hidden_alias

    shown = [n for n in (installed or ()) if n and not is_hidden_alias(n)][:5]
    if shown:
        sentence += f" (installed: {', '.join(shown)})"
    return sentence + "."


async def _ollama_precheck(family: Any, model: str, read_state: Any) -> tuple[str, str] | None:
    """Fail fast with the cause when the Ollama card cannot answer at all.

    Without this the card waited the full ceiling and then said only "No answer
    within 8s." for a stopped server or a model that was never pulled (#809),
    which reads like a broken app. Returns ``(status, detail)`` or None when
    the call is worth making. A lookup that itself fails returns None: the real
    call then decides, exactly as before.
    """
    try:
        state = await read_state(family)
    except Exception as exc:  # noqa: BLE001 — a diagnosis must never become the verdict
        log.debug("polish probe: Ollama state lookup failed (%s)", exc)
        return None
    if not state.get("reachable"):
        return (
            "unreachable",
            f"Ollama did not answer at {state.get('root', '')}. Start Ollama, "
            "then press Test again.",
        )
    if model and not _has_model(state.get("installed"), model):
        return ("model_unavailable", _missing_model_sentence(model, state.get("installed")))
    return None


async def _ollama_timeout_detail(family: Any, model: str, ceiling_s: float, read_state: Any) -> str:
    """Turn an Ollama timeout into its likely cause and the next step."""
    head = f"No answer within {ceiling_s:.0f}s."
    try:
        state = await read_state(family)
    except Exception as exc:  # noqa: BLE001
        log.debug("polish probe: Ollama state lookup failed (%s)", exc)
        return head
    loaded = state.get("loaded")
    if loaded is None or not model:
        return head
    if not _has_model(loaded, model):
        return (
            f"{head} Ollama was still loading '{model}' into memory; the first "
            "answer after a start takes longer. Press Test again in a moment."
        )
    return (
        f"{head} '{model}' is loaded but answers too slowly on this machine. "
        "Pick a smaller model or a hosted provider for dictation wording."
    )


async def probe_polish_family(
    family: Any,
    cfg: Any,
    *,
    make_client: Any | None = None,
    model: str = "",
    read_ollama_state: Any | None = None,
) -> Any:
    """Run ONE real formatting call through *family* and classify the outcome.

    *cfg* is the whole app config; only ``cfg.dictation`` is read (for the
    latency budget and the model pin). Returns a
    ``dodaios.brain.provider_test.ProviderTestResult``. Never raises: a probe
    that blows up must produce a verdict, not an exception the card cannot
    render.
    """
    from dodaios.brain.provider_test import (
        ERROR,
        NOT_CONFIGURED,
        OK,
        UNREACHABLE,
        ProviderTestResult,
        classify_provider_error,
    )

    provider = ""
    dictation_cfg = getattr(cfg, "dictation", None)
    try:
        from dodaios.ui.web.provider_spec import dictation_spec_id

        provider = dictation_spec_id(str(getattr(family, "id", "")))
    except Exception:  # noqa: BLE001 — the card id is cosmetic here
        provider = str(getattr(family, "id", ""))

    if family is None:
        return ProviderTestResult(
            provider, ERROR, "This card has no provider family behind it."
        )

    budget_ms = float(getattr(dictation_cfg, "polish_timeout_ms", 0) or _DEFAULT_BUDGET_MS)
    probe_model = _resolve_probe_model(family, dictation_cfg, model)

    builder = make_client or _default_make_client
    try:
        client = builder(family, probe_model)
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        return ProviderTestResult(provider, classify_provider_error(detail), str(exc))
    if client is None:
        # ``build_polish_client`` answers None for "no credential" and for "the
        # SDK this transport needs is not installed" — ordinary states on some
        # install, neither of them an integration bug.
        return ProviderTestResult(
            provider,
            NOT_CONFIGURED,
            "No usable credential or transport for this provider.",
        )

    is_ollama = str(getattr(family, "endpoint_provider", "") or "") == "ollama"
    read_state = read_ollama_state or _default_ollama_state
    if is_ollama:
        verdict = await _ollama_precheck(family, probe_model, read_state)
        if verdict is not None:
            return ProviderTestResult(provider, verdict[0], verdict[1])

    ceiling_s = max(budget_ms / 1000.0 * _CEILING_FACTOR, _CEILING_FLOOR_S)
    started = perf_counter()
    try:
        text = await asyncio.wait_for(
            client.complete(
                PROBE_SYSTEM,
                PROBE_USER,
                # Reasoning-capable providers count hidden work against this
                # ceiling too. 64 tokens can therefore yield HTTP 200 with no
                # visible text; 256 remains small for a one-sentence probe while
                # leaving room for the final answer.
                max_output_tokens=256,
                temperature=0.0,
                timeout_s=ceiling_s,
            ),
            timeout=ceiling_s,
        )
    except TimeoutError:
        # Not silent: the timeout becomes the card's visible verdict, which is
        # the whole point of the probe. A log line would duplicate what the user
        # is about to read on screen.
        elapsed = (perf_counter() - started) * 1000.0
        detail = f"No answer within {ceiling_s:.0f}s."
        if is_ollama:
            detail = await _ollama_timeout_detail(family, probe_model, ceiling_s, read_state)
        return ProviderTestResult(provider, UNREACHABLE, detail, elapsed)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a verdict
        elapsed = (perf_counter() - started) * 1000.0
        detail = f"{type(exc).__name__}: {exc}"
        return ProviderTestResult(
            provider, classify_provider_error(detail), str(exc), elapsed
        )

    elapsed = (perf_counter() - started) * 1000.0
    if not (text or "").strip():
        return ProviderTestResult(provider, ERROR, "Answered with no text.", elapsed)
    if elapsed > budget_ms:
        # Reached, authenticated, answered — and still unusable HERE, which is
        # the only thing the user cares about. The sentence carries the
        # measurement, the budget AND the fix, because choosing between "raise
        # the limit" and "pick a faster provider" is the user's call.
        return ProviderTestResult(
            provider,
            UNREACHABLE,
            (
                f"Answered in {elapsed:.0f} ms — slower than the {budget_ms:.0f} ms "
                "wording limit, so dictation would deliver the raw text. Raise the "
                "limit or pick a faster provider."
            ),
            elapsed,
        )
    return ProviderTestResult(provider, OK, f"Answered in {elapsed:.0f} ms.", elapsed)


__all__ = ["PROBE_SYSTEM", "PROBE_USER", "probe_polish_family"]
