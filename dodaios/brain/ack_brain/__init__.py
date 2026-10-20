"""Pre-Thinking-Ack Flash-Brain module.

See docs/superpowers/specs/2026-05-11-pre-thinking-ack-flash-brain-design.md
for the full design. Public surface:

- persona_prompt:    PERSONA_PROMPT constant + get_persona_prompt(language)
- config:            AckBrainConfig pydantic model
- providers:         four provider adapters + AbstractAckProvider Protocol
- generator:         AckGenerator (single-shot orchestrator with F10 post-filter)
- circuit_breaker:   CircuitBreaker async-safe three-state machine
- spawn_announcement: SpawnAnnouncementComposer (dynamic worker-spawn ACKs,
                      NOT part of the locked 2026-05-11 flash-brain spec)

Factory wiring in P3 will read cfg.ack_brain, instantiate a provider
from providers.REGISTRY, build a CircuitBreaker, and thread the
resulting AckGenerator into BrainManager.
"""
from __future__ import annotations

from dodaios.brain.ack_brain.circuit_breaker import CircuitBreaker
from dodaios.brain.ack_brain.generator import AckGenerator
from dodaios.brain.ack_brain.persona_prompt import PERSONA_PROMPT, get_persona_prompt
from dodaios.brain.ack_brain.spawn_announcement import SpawnAnnouncementComposer

__all__ = [
    "AckGenerator",
    "CircuitBreaker",
    "PERSONA_PROMPT",
    "SpawnAnnouncementComposer",
    "get_persona_prompt",
]
