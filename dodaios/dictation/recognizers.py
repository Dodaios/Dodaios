"""Which recognizers read a dictation on this computer, in which order.

The answer is a short list of engines that really exist here, each under the
name of what runs. A cloud provider is on the list only while a key for it is
saved; an on-device engine only while its runtime and model are installed.
Nothing stands on the list as a placeholder for something else.

The order:

1. **The person chose an on-device recognizer** (``[stt].provider`` is local):
   only on-device engines, the chosen one first. No audio leaves the computer,
   whatever keys are saved.
2. **Local Whisper with a graphics card that answers:** that engine first, the
   cloud provider behind it.
3. **Otherwise:** the cloud provider with a saved key first, the best
   on-device engine behind it as the stand-in.
4. **No key at all:** the on-device engines alone.

Among on-device engines without a graphics card the one-pass Parakeet model
leads where it is downloaded and covers the language: on a plain CPU it reads
a recording many times faster than Whisper does.

:func:`credential_signature` changes whenever a key is saved or removed, so a
caller that keeps a resolution can tell when to resolve again. That is what
makes a pasted key count from the next dictation on, without a restart.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dodaios.dictation.take import Recognizer

log = logging.getLogger("dodaios.dictation.recognizers")

PARAKEET_ID = "parakeet-local"
WHISPER_ID = "faster-whisper"


@dataclass(frozen=True, slots=True)
class Resolution:
    """The recognizers for the next dictation and one sentence about them.

    ``detail`` is for the person: why recognition is slower or elsewhere than
    the settings suggest, and what would change it. Empty when there is
    nothing to say.
    """

    recognizers: tuple[Recognizer, ...] = ()
    detail: str = ""
    #: The same fact as ``detail`` as a code a surface can translate:
    #: ``no_recognizer``, ``no_key``, ``no_key_slow``, ``other_provider``.
    reason: str = ""
    #: The provider the settings name, whatever reads in its place.
    configured: str = ""

    def status(self) -> dict[str, Any]:
        """The shape the dictation status route serves."""
        first = self.recognizers[0] if self.recognizers else None
        second = self.recognizers[1] if len(self.recognizers) > 1 else None
        return {
            "local": bool(first.on_device) if first else False,
            "provider": first.id if first else "",
            "model": first.model if first else "",
            "fallback": second.id if second else "",
            "detail": self.detail,
            "reason": self.reason,
            "configured": self.configured,
        }


def credential_signature(stt_cfg: Any) -> str:
    """A value that changes when a speech-to-text key is saved or removed."""
    try:
        from dodaios.core import config as _cfg
        from dodaios.plugins.stt import _STT_SECRET_CANDIDATES
    except Exception:  # noqa: BLE001 - no plugin layer means nothing to sign
        return ""
    digest = hashlib.sha256()
    digest.update(str(getattr(stt_cfg, "provider", "") or "").encode())
    for name in sorted(_STT_SECRET_CANDIDATES):
        try:
            secret = _cfg.get_secret_any(_STT_SECRET_CANDIDATES[name])
        except Exception:  # noqa: BLE001 - an unreadable store reads as "no key"
            secret = None
        digest.update(name.encode())
        digest.update(hashlib.sha256(str(secret or "").encode()).digest())
    return digest.hexdigest()


def parakeet_ready() -> bool:
    """Whether the Parakeet runtime and model are both on this computer."""
    try:
        import importlib.util

        if importlib.util.find_spec("sherpa_onnx") is None:
            return False
        from dodaios.plugins.stt.parakeet_local import MODEL_ID
        from dodaios.speech.sherpa_models import model_paths

        paths = model_paths(MODEL_ID)
        return bool(paths) and all(path.is_file() for path in paths.values())
    except Exception:  # noqa: BLE001 - a failed probe means "not ready"
        log.debug("dictation: Parakeet readiness probe failed", exc_info=True)
        return False


def _language_code(language: str) -> str:
    return str(language or "").strip().lower().replace("_", "-").split("-", 1)[0]


def _parakeet_covers(language: str) -> bool:
    code = _language_code(language)
    if not code or code == "auto":
        return True
    try:
        from dodaios.plugins.stt.parakeet_local import supports_language

        return supports_language(code)
    except Exception:  # noqa: BLE001 - without the plugin the model covers nothing
        return False


def resolve_recognizers(
    stt_cfg: Any,
    *,
    language: str = "auto",
    cloud: Callable[[str], Any | None],
    keyed_cloud_names: Callable[[], list[str]],
    runs_on_device: Callable[[str], bool],
    whisper_worker: Any | None = None,
    whisper_has_accelerator: bool = False,
    parakeet: Callable[[], Any | None] | None = None,
    configured_local: Callable[[str], Any | None] | None = None,
    whisper_in_process: Callable[[], Any | None] | None = None,
    wrap: Callable[[Any], Any] | None = None,
) -> Resolution:
    """Build the list. Every builder may return ``None`` for "not here".

    ``language`` is the language the dictation is expected in (a code, or
    ``auto``). ``cloud(name)`` builds the cloud provider ``name``;
    ``keyed_cloud_names()`` lists the cloud providers a key is saved for, the
    preferred one first. ``whisper_worker`` is the out-of-process Whisper
    engine, ``whisper_in_process`` the same model inside the app for a host
    without the worker. ``wrap`` is put around every provider (vocabulary
    corrections, usage metering).
    """
    configured = str(getattr(stt_cfg, "provider", "") or "").strip()
    wrap = wrap or (lambda provider: provider)
    chosen_local = bool(configured) and runs_on_device(configured)

    on_device: list[Recognizer] = []

    def add_local(recognizer_id: str, provider: Any | None, model: str = "") -> None:
        if provider is None or any(r.id == recognizer_id for r in on_device):
            return
        on_device.append(
            Recognizer(
                id=recognizer_id,
                provider=wrap(provider),
                model=model or str(getattr(provider, "last_used_model", "") or ""),
                on_device=True,
            )
        )

    parakeet_instance = parakeet() if parakeet is not None else None
    parakeet_fits = parakeet_instance is not None and _parakeet_covers(language)

    if chosen_local and configured not in (WHISPER_ID, PARAKEET_ID):
        # Another on-device engine picked by name leads; the others stand in.
        add_local(configured, configured_local(configured) if configured_local else None)
    if chosen_local and configured == PARAKEET_ID and parakeet_instance is not None:
        add_local(PARAKEET_ID, parakeet_instance)
    whisper_first = whisper_worker is not None and (
        whisper_has_accelerator or (chosen_local and configured == WHISPER_ID)
    )
    if whisper_first:
        add_local(WHISPER_ID, whisper_worker)
    if parakeet_fits:
        add_local(PARAKEET_ID, parakeet_instance)
    if whisper_worker is not None:
        add_local(WHISPER_ID, whisper_worker)
    elif whisper_in_process is not None and not on_device:
        add_local(WHISPER_ID, whisper_in_process())

    cloud_recognizer: Recognizer | None = None
    cloud_name = ""
    if not chosen_local:
        keyed = [name for name in keyed_cloud_names() if not runs_on_device(name)]
        cloud_name = configured if configured in keyed else (keyed[0] if keyed else "")
        provider = cloud(cloud_name) if cloud_name else None
        if provider is not None:
            cloud_recognizer = Recognizer(
                id=cloud_name,
                provider=wrap(provider),
                model=str(getattr(provider, "last_used_model", "") or ""),
                on_device=False,
            )

    recognizers: list[Recognizer] = []
    if cloud_recognizer is None:
        recognizers = on_device[:2]
    elif whisper_has_accelerator and on_device and on_device[0].id == WHISPER_ID:
        recognizers = [on_device[0], cloud_recognizer]
    else:
        recognizers = [cloud_recognizer, *on_device[:1]]

    detail = ""
    reason = ""
    first = recognizers[0] if recognizers else None
    if first is None:
        reason = "no_recognizer"
        detail = (
            "No speech recognition is set up on this computer. Save a provider "
            "key or download an on-device model under Voice > API Keys."
        )
    elif not chosen_local and cloud_recognizer is None:
        reason = "no_key"
        detail = (
            f"No key is saved for {configured or 'a speech provider'}, so "
            "recognition runs on this computer."
        )
        if first.id == WHISPER_ID and not whisper_has_accelerator and parakeet_instance is None:
            reason = "no_key_slow"
            detail += (
                " Whisper is slow without a graphics card: the Parakeet model "
                "under Voice > API Keys (about 490 MB) is many times faster."
            )
    elif cloud_recognizer is not None and cloud_name != configured:
        reason = "other_provider"
        detail = (
            f"No key is saved for {configured}; {cloud_name} recognizes instead."
        )
    return Resolution(
        recognizers=tuple(recognizers), detail=detail, reason=reason, configured=configured
    )


__all__ = [
    "PARAKEET_ID",
    "WHISPER_ID",
    "Resolution",
    "credential_signature",
    "parakeet_ready",
    "resolve_recognizers",
]
