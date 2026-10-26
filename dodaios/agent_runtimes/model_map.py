"""Map a society agent's Jarvis provider + model onto an external runtime.

An agent on Hermes or OpenClaw reaches its model through Jarvis' own model
gateway (``gateway.py``): the runtime is configured with one provider —
Jarvis, on the app's loopback server — and a per-agent token in its process
environment (:data:`KEY_ENV_VAR`). Jarvis answers with its own provider
plugins, so the runtime never holds a vendor key or login and its config is
the same for every provider. API-key and local providers speak Chat
Completions; the ChatGPT subscription (``openai-codex``) speaks Responses.

The Claude subscription is the one exception (transport ``claude_cli``).
Anthropic bills a Claude login sent to its HTTP API by a third-party app as
Extra Usage, never from the plan, so that login is never sent there: the
runtime runs the official Claude CLI itself (OpenClaw's bundled
``claude-cli`` backend), and the CLI owns the login and its renewal. The
route carries only which CLI to run and which Claude account directory it
reads; no bearer and no API key.

This module decides which providers an agent can use right now (a saved key,
a local server with an address, a signed-in subscription) and builds the
route. Claude runs on an Anthropic API key, or on the Claude subscription
when the agent is pinned to it or no key is saved.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

log = logging.getLogger(__name__)

Transport = Literal["chat_completions", "anthropic_messages", "responses", "claude_cli"]

#: The environment variable both runtimes read the model key from.
KEY_ENV_VAR: Final[str] = "JARVIS_RUNTIME_API_KEY"

#: A Claude subscription (OAuth) token, never an Anthropic API key.
_CLAUDE_LOGIN_PREFIX: Final[str] = "sk-ant-oat"

#: The provider name Jarvis registers inside the runtime's config.
RUNTIME_PROVIDER_NAME: Final[str] = "jarvis"


@dataclass(frozen=True, slots=True)
class _Endpoint:
    #: Vendor default base URL; ``None`` = the person must configure one.
    default_base_url: str | None
    keyless: bool = False
    #: A local server: it needs a server address the person configured.
    local_server: bool = False
    #: Served by Jarvis' own model gateway on the person's subscription.
    subscription: bool = False
    #: Without an API key (or pinned to it), the person's Claude subscription
    #: answers instead, through the official Claude CLI only.
    claude_login: bool = False
    #: May authenticate without a key: Google Cloud Application Default
    #: Credentials for a configured project (Vertex AI).
    cloud_project: bool = False


#: Jarvis provider id (``agent_chat.catalog`` / ``core.config``) -> endpoint.
_ENDPOINTS: Final[dict[str, _Endpoint]] = {
    "claude-api": _Endpoint("https://api.anthropic.com", claude_login=True),
    "openai": _Endpoint("https://api.openai.com/v1"),
    "grok": _Endpoint("https://api.x.ai/v1"),
    "openrouter": _Endpoint("https://openrouter.ai/api/v1"),
    "nvidia": _Endpoint("https://integrate.api.nvidia.com/v1"),
    "gemini": _Endpoint("https://generativelanguage.googleapis.com/v1beta/openai"),
    "vertex": _Endpoint("https://aiplatform.googleapis.com", cloud_project=True),
    "ollama": _Endpoint(None, keyless=True, local_server=True),
    "local-openai": _Endpoint(None, keyless=True, local_server=True),
    "openai-codex": _Endpoint(None, subscription=True),
}


class RouteUnavailable(Exception):
    """The agent's model cannot run on the runtime; the message is user-facing."""


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """Everything a runtime config needs to reach the agent's model."""

    provider: str
    model: str
    base_url: str
    transport: Transport
    #: ``None`` for a keyless local server and for the Claude CLI.
    api_key: str | None
    context_window: int = 32_768
    max_output_tokens: int | None = None
    #: ``claude_cli`` only: the official Claude CLI the runtime runs.
    claude_binary: str = ""
    #: ``claude_cli`` only: the environment that selects the agent's Claude
    #: account (its config directory). Never a credential.
    claude_env: tuple[tuple[str, str], ...] = ()

    def env(self) -> dict[str, str]:
        """The child environment: the key (empty when keyless), or for the
        Claude CLI only the account selection."""
        if self.transport == "claude_cli":
            return dict(self.claude_env)
        return {KEY_ENV_VAR: self.api_key} if self.api_key else {}


def supported_providers() -> frozenset[str]:
    """Jarvis providers an external runtime can run on (no secrets read)."""
    return frozenset(_ENDPOINTS)


def subscription_providers() -> frozenset[str]:
    """Providers served by Jarvis' model gateway on the person's subscription."""
    return frozenset(name for name, endpoint in _ENDPOINTS.items() if endpoint.subscription)


@dataclass(frozen=True, slots=True)
class ClaudeLogin:
    """A signed-in Claude subscription the official CLI can run on."""

    #: The Claude CLI executable.
    binary: str
    #: What selects the account in the CLI's environment (``CLAUDE_CONFIG_DIR``;
    #: empty for the platform default). Never a credential.
    env: tuple[tuple[str, str], ...] = ()


def _claude_account_env(account_id: str) -> dict[str, str]:
    """The environment that points the Claude CLI at the agent's account.

    ``account_id`` may name a Claude login (``dodaios.agent_accounts``);
    anything else (``""``, a reserved access value) means the active Claude
    account. The built-in account adds nothing, so the CLI keeps its platform
    default (the macOS Keychain, for one) — unless this app itself runs with
    a ``CLAUDE_CONFIG_DIR``, which a runtime's minimal child environment
    would otherwise drop.
    """
    from dodaios import agent_accounts
    from dodaios.agent_chat.catalog import ACCESS_ACCOUNTS

    named = account_id if account_id and account_id not in ACCESS_ACCOUNTS else ""
    account = agent_accounts.resolve(named) if named else agent_accounts.active_account("claude")
    if account is None or account.platform != "claude":
        account = agent_accounts.active_account("claude")
    env = agent_accounts.env_overrides("claude", account.id)
    inherited = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if not env and inherited:
        env = {"CLAUDE_CONFIG_DIR": inherited}
    return env


def claude_login(account_id: str = "") -> ClaudeLogin:
    """The Claude subscription the agent runs on, checked with the CLI itself.

    Only ``claude auth status`` is asked, under the same minimal environment
    the runtime gives its CLI: no credential is read and no bearer leaves the
    CLI. Raises :class:`RouteUnavailable` with the reason in plain words.
    Blocking (one short process, cached a few seconds).
    """
    from dodaios.agent_runtimes.base import child_env
    from dodaios.claude_auth import (
        claude_install_hint,
        cli_login_env,
        is_subscription_login,
        native_subscription_login,
    )

    selection = _claude_account_env(account_id)
    env = cli_login_env(child_env(selection))
    binary, login = native_subscription_login(env)
    if binary is None:
        raise RouteUnavailable(
            "This agent runs on the Claude subscription, which Dodaios uses only through "
            f"Claude Code, and Claude Code is not installed. {claude_install_hint()} "
            "No API key was used."
        )
    if not is_subscription_login(login):
        raise RouteUnavailable(
            "This agent runs on the Claude subscription, which Dodaios uses only through "
            "Claude Code, and Claude Code is not signed in to a Claude plan. Sign in to "
            "Claude Code (Settings → API keys), or switch the agent to an Anthropic API "
            "key. No API key was used."
        )
    if env.get("USER"):
        # The CLI's native credential lookup needs it (POSIX).
        selection.setdefault("USER", env["USER"])
    return ClaudeLogin(binary=binary, env=tuple(sorted(selection.items())))


def _api_key(provider: str, credential: str | None) -> str | None:
    """The provider's real API key (the Agents-tier key wins), never a login."""
    from dodaios.core.config import get_jarvis_agent_secret

    key = (get_jarvis_agent_secret(provider) or credential or "").strip() or None
    if key is not None and provider == "claude-api" and key.startswith(_CLAUDE_LOGIN_PREFIX):
        # A Claude subscription login saved in the API-key slot is not an API
        # key: Anthropic's API refuses it as one ("OAuth access token is invalid").
        return None
    return key


def _saved_key(provider: str, endpoint: _Endpoint) -> str | None:
    from dodaios.core.config import resolve_provider_endpoint

    resolved = resolve_provider_endpoint(
        provider, vendor_default_base_url=endpoint.default_base_url
    )
    return _api_key(provider, resolved.credential)


def uses_claude_cli(provider: str, account_id: str = "") -> bool:
    """Whether ``provider`` answers on the Claude subscription for
    ``account_id``, which only the official Claude CLI may use. ``account_id``
    may pin the agent to its key or to the subscription
    (``catalog.ACCESS_ACCOUNTS``); without a pin the API key wins. A
    subscription seat stays one when its login is gone: it is reported as
    such, never answered on a key. Blocking (keyring)."""
    from dodaios.agent_chat.catalog import API_KEY_ACCOUNT, SUBSCRIPTION_ACCOUNT

    endpoint = _ENDPOINTS.get(provider)
    if endpoint is None or not endpoint.claude_login or account_id == API_KEY_ACCOUNT:
        return False
    return account_id == SUBSCRIPTION_ACCOUNT or _saved_key(provider, endpoint) is None


def _claude_login_ready(account_id: str = "") -> bool:
    try:
        claude_login(account_id)
    except RouteUnavailable:  # not installed or not signed in: not offered
        return False
    return True


def access_choices() -> dict[str, list[str]]:
    """Per provider that can pay two ways (Claude: API key or the Claude
    subscription through Claude Code), the ways that work right now: ``"api"``
    and/or ``"subscription"``. The "New agent" dialog offers exactly these.
    Blocking (keyring, ``claude auth status``)."""
    choices: dict[str, list[str]] = {}
    for name, endpoint in _ENDPOINTS.items():
        if not endpoint.claude_login:
            continue
        found: list[str] = []
        if _saved_key(name, endpoint) is not None:
            found.append("api")
        if _claude_login_ready():
            found.append("subscription")
        if found:
            choices[name] = found
    return choices


def supports(provider: str) -> bool:
    return provider in _ENDPOINTS


def is_local(provider: str) -> bool:
    """Whether ``provider`` is a model server the person runs themselves."""
    endpoint = _ENDPOINTS.get(provider)
    return endpoint is not None and endpoint.local_server


def usable_providers(config: Any) -> list[str]:
    """Supported providers that can run right now: a saved key, a keyless
    local server with an address, or a signed-in subscription (listed
    first: it spends no API key). Blocking (keyring): call it in a thread.
    """
    usable: list[str] = []
    for provider in sorted(_ENDPOINTS, key=lambda name: (not _ENDPOINTS[name].subscription, name)):
        try:
            _checked_model(config, provider, "probe")
        except RouteUnavailable:  # not connected: the provider is simply not offered
            continue
        except Exception:  # noqa: BLE001 — one unreadable provider must not empty the list
            log.warning("agent runtimes: provider %s could not be checked", provider, exc_info=True)
            continue
        usable.append(provider)
    return usable


def _default_model(config: Any, provider: str) -> str:
    providers = getattr(getattr(config, "brain", None), "providers", None) or {}
    configured = str(getattr(providers.get(provider), "model", "") or "")
    if configured:
        return configured
    from dodaios.brain.manager import get_tier_default_model

    return get_tier_default_model("router", provider) or ""


def _local_root(provider: str, configured: str | None) -> str | None:
    if provider == "ollama":
        from dodaios.plugins.brain.ollama import default_server_root, normalize_server_root

        return normalize_server_root(configured or default_server_root())
    if configured:
        from dodaios.plugins.brain.ollama import normalize_server_root

        return normalize_server_root(configured)
    return None


def _checked_model(config: Any, provider: str, model: str, *, account_id: str = "") -> str:
    """The model the agent runs on, once the provider is known to be able to
    answer; raises :class:`RouteUnavailable` with the reason in plain words."""
    endpoint = _ENDPOINTS.get(provider)
    if endpoint is None:
        raise RouteUnavailable(
            f"The {provider or 'selected'} seat cannot drive Hermes or OpenClaw. "
            "Pick a model that runs on an API key, a local server or the ChatGPT "
            "subscription."
        )
    if endpoint.subscription:
        from dodaios.agent_runtimes import gateway

        if not gateway.subscription_ready(account_id):
            raise RouteUnavailable(
                "The ChatGPT subscription is not signed in. Connect it in Settings → API "
                "keys first."
            )
        chosen = model.strip() or _default_model(config, provider)
        if not chosen:
            # The agent was created without a model: Codex's own first pick.
            from dodaios.agent_chat.catalog import CODEX_FALLBACK_MODELS

            chosen = CODEX_FALLBACK_MODELS[0].id if CODEX_FALLBACK_MODELS else ""
        if not chosen:
            raise RouteUnavailable("Choose a ChatGPT model for this agent first.")
        return chosen
    if endpoint.claude_login and uses_claude_cli(provider, account_id):
        claude_login(account_id)
        chosen = model.strip() or _default_model(config, provider)
        if not chosen:
            raise RouteUnavailable("Choose a Claude model for this agent first.")
        return chosen
    from dodaios.core.config import resolve_provider_endpoint

    resolved = resolve_provider_endpoint(
        provider, vendor_default_base_url=endpoint.default_base_url
    )
    base_url = resolved.base_url
    if endpoint.local_server and not resolved.via_proxy:
        base_url = _local_root(provider, base_url)
    if not base_url:
        raise RouteUnavailable(
            f"{provider} has no server address yet. Add it on the provider's card first."
        )
    # The Agents-tier key wins over the shared one, exactly as the gateway uses it.
    key = _api_key(provider, resolved.credential)
    if endpoint.claude_login and key is None:
        # Only an agent pinned to its key gets here without one.
        raise RouteUnavailable(
            "This agent runs on an Anthropic API key, and none is saved. Connect "
            "one in Settings → API keys, or switch the agent to the subscription."
        )
    if key is None and endpoint.cloud_project:
        from dodaios.core.config import vertex_credential_configured

        if vertex_credential_configured():
            key = ""  # the Cloud project signs the requests (no key)
    if key is None and not endpoint.keyless:
        raise RouteUnavailable(
            f"No API key is saved for {provider}. Connect it in Settings → API keys."
        )
    chosen = model.strip() or _default_model(config, provider)
    if not chosen:
        raise RouteUnavailable(f"Choose a model for {provider} first.")
    return chosen


def _claude_cli_route(config: Any, provider: str, model: str, account_id: str) -> ModelRoute:
    """The route of an agent on the Claude subscription: the official CLI,
    run by the runtime itself. No gateway token: nothing of this agent's can
    reach Anthropic's HTTP API, which bills a third-party login as Extra Usage."""
    from dodaios.agent_runtimes.model_limits import resolve_limits
    from dodaios.brain.model_catalog import ModelCatalog

    login = claude_login(account_id)
    chosen = model.strip() or _default_model(config, provider)
    if not chosen:
        raise RouteUnavailable("Choose a Claude model for this agent first.")
    limits = resolve_limits(config, provider, chosen, ModelCatalog().cached_model(provider, chosen))
    return ModelRoute(
        provider=provider,
        model=chosen,
        base_url="",
        transport="claude_cli",
        api_key=None,
        context_window=limits.context_window,
        max_output_tokens=limits.max_output_tokens,
        claude_binary=login.binary,
        claude_env=login.env,
    )


def route_for(
    config: Any,
    provider: str,
    model: str,
    *,
    agent_id: str = "",
    account_id: str = "",
    session_id: str = "",
) -> ModelRoute:
    """The agent's route through Jarvis' gateway. Blocking (keyring): call it
    in a thread. The token speaks for ``agent_id`` on ``provider`` (and, for
    the subscription, on that Codex ``account_id``). An agent on the Claude
    subscription gets the Claude CLI route instead (:func:`_claude_cli_route`)."""
    if uses_claude_cli(provider, account_id):
        return _claude_cli_route(config, provider, model, account_id)
    chosen = _checked_model(config, provider, model, account_id=account_id)
    from dodaios.agent_runtimes import gateway
    from dodaios.agent_runtimes.base import home_key
    from dodaios.agent_runtimes.model_limits import resolve_limits
    from dodaios.brain.model_catalog import ModelCatalog

    try:
        gateway.check_cooldown(provider, chosen, account_id)
    except gateway.GatewayError as exc:
        raise RouteUnavailable(str(exc)) from exc
    base_url = gateway.base_url()
    if not base_url:
        raise RouteUnavailable("Dodaios' model gateway is not up yet. Try again in a moment.")
    limits = resolve_limits(config, provider, chosen, ModelCatalog().cached_model(provider, chosen))
    token = gateway.grant_token(
        agent_id, provider, account_id,
        scope=home_key(agent_id, session_id) if session_id else "",
        require_active_turn=True,
    )
    gateway.register_model(token, chosen, limits)
    return ModelRoute(
        provider=provider,
        model=chosen,
        base_url=base_url,
        transport="responses" if _ENDPOINTS[provider].subscription else "chat_completions",
        api_key=token,
        context_window=limits.context_window,
        max_output_tokens=limits.max_output_tokens,
    )


async def prepare_route(
    config: Any, provider: str, model: str, *, agent_id: str = "", account_id: str = "",
    session_id: str = "",
) -> ModelRoute:
    """Refresh catalog metadata before writing either runtime's configuration."""
    from dodaios.agent_runtimes import gateway

    route = await asyncio.to_thread(
        route_for, config, provider, model, agent_id=agent_id, account_id=account_id,
        session_id=session_id,
    )
    if route.transport == "claude_cli":
        return route
    assert route.api_key is not None
    grant = gateway.verify(route.api_key)
    assert grant is not None
    limits = await gateway.refresh_model_limits(grant, route.model, config)
    gateway.register_model(route.api_key, route.model, limits)
    return replace(
        route, context_window=limits.context_window, max_output_tokens=limits.max_output_tokens
    )
