"""Explicit, secret-free GPT-Live setup and model selection.

The saved selection lives here, in core, because ``JarvisConfig.live`` holds it.
The session text itself (prompt rules, tool wiring) is built in
``dodaios.live.config`` and imported on first use, so loading the config does
not load the live prompt rules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LiveConfig(BaseModel):
    """A saved selection, never an implicit opt-in to a billed model."""

    model_config = ConfigDict(extra="forbid")
    model: str = "gpt-live-1"
    voice: str = "gleam"
    backend_model: str = ""
    reasoning_effort: str = "medium"
    web_search: bool = True
    instructions: str = Field(default="", max_length=8000)
    backend_instructions: str = Field(default="", max_length=32000)
    configured: bool = False
    auth_mode: Literal["api_key", "chatgpt_subscription"] = "api_key"
    subscription_account_id: str = Field(default="", max_length=256)
    subscription_voice: str = "cove"
    subscription_backend_model: str = ""
    subscription_reasoning_effort: str = "medium"

    @property
    def provider_id(self) -> str:
        if self.auth_mode == "chatgpt_subscription":
            return "openai-live-subscription"
        return "openai-live"

    def for_session(self) -> LiveConfig:
        """Snapshot the selected mode without overwriting the other mode's settings."""
        if self.auth_mode == "api_key":
            return self.model_copy()
        return self.model_copy(
            update={
                "model": "gpt-live-1-codex",
                "voice": self.subscription_voice,
                "backend_model": self.subscription_backend_model,
                "reasoning_effort": self.subscription_reasoning_effort,
            }
        )

    def backend_config(self, *, language: str, tools: list[dict], identity: str = "") -> dict:
        """Use the same Jarvis instructions and tools for client-managed reasoning."""
        effective = self.for_session().model_copy(update={"auth_mode": "api_key"})
        return effective.session_config(language=language, tools=tools, identity=identity)[
            "delegation"
        ]["responses"]

    def session_config(self, *, language: str, tools: list[dict], identity: str = "") -> dict:
        """The GPT-Live session; ``identity`` is ``dodaios.brain.identity.identity_block``."""
        from dodaios.live.config import build_session_config

        return build_session_config(self, language=language, tools=tools, identity=identity)
