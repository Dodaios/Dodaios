"""Credential requests that park a turn until the person connects."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.credential_requests import (
    CREDENTIAL_TIMEOUT_S,
    CredentialRequests,
    CredentialSpec,
)

if TYPE_CHECKING:
    from dodaios.agent_chat.service_parts._host_state import AgentChatHostState as _HostBase
else:
    _HostBase = object


class CredentialsMixin(_HostBase):
    """Credential requests that park a turn until the person connects."""

    # ------------------------------------------------------------ credentials

    @staticmethod
    def _restore_credential_save(
        session_id: str, spec: CredentialSpec, owner: str | None = None
    ) -> Callable | None:
        """Rebuild only a Society field's save callback, never a stored secret.

        ``owner`` is the vault of a chat that is no society seat's: the lead's
        own chat keeps the owner's secrets (``_vault_owner``).
        """
        from dodaios.agent_chat.credential_requests import CLI, LOGIN, PLUGIN
        from dodaios.society.credentials import (
            login_key,
            login_site,
            save_requested_credential,
            save_requested_login,
            validate_env_name,
        )
        from dodaios.society.surface import agent_id_of

        if spec.kind in (PLUGIN, CLI):
            # A Connect card stores nothing for an agent, so every chat that
            # showed one gets it back: the lead's chat and a coding thread too.
            from dodaios.society.connect_tool import connect_save

            return connect_save(spec.kind, spec.env)
        agent_id = agent_id_of(session_id) or owner
        if agent_id is None:
            return None
        try:
            if spec.kind == LOGIN:
                login_key(spec.env)
                login_site(spec.url)
            else:
                validate_env_name(spec.env)
        except ValueError:
            _s.log.warning("agent chat: ignored invalid stored credential field metadata")
            return None

        async def save(value: str) -> None:
            if spec.kind == LOGIN:
                await save_requested_login(
                    agent_id, spec.env, value, url=spec.url, label=spec.label
                )
            else:
                await save_requested_credential(
                    agent_id,
                    spec.env,
                    value,
                    label=spec.label,
                    kind=spec.secret_kind,
                    note=spec.description or None,
                )

        return save

    def _running_turn_id(self, session_id: str) -> str | None:
        run = self._running.get(session_id)
        if run is None or run.task is None or run.task.done():
            return None
        return run.turn_id

    async def open_credential_request(
        self,
        session_id: str,
        spec: CredentialSpec,
        save: Callable[[str], Any],
        *,
        asker: str = "",
        timeout_s: float = CREDENTIAL_TIMEOUT_S,
        renew: bool = False,
    ) -> str:
        """Show a secure credential field in the running turn; returns its request id.

        ``save`` receives the pasted value and is its only destination. Raises
        ``RuntimeError`` without a running turn and ``TooManyCredentialRequests``
        once the turn used its cards. ``renew`` shows a field an earlier turn
        left open again in this one.
        """
        return await self._credentials.open(
            session_id, spec, save, asker=asker, timeout_s=timeout_s, renew=renew
        )

    async def wait_credential_request(
        self, session_id: str, request_id: str, timeout_s: float | None = None
    ) -> str | None:
        """``saved`` or ``declined``, or ``None`` while the field remains open."""
        return await self._credentials.wait(session_id, request_id, timeout_s)

    def credential_request_spec(self, session_id: str, request_id: str) -> CredentialSpec:
        return self._credentials.spec(session_id, request_id)

    async def restore_credential_requests(self, session_id: str) -> None:
        await self._credentials.restore(session_id)

    async def submit_credential(self, session_id: str, request_id: str, value: str) -> bool:
        """The person's pasted value; ``ValueError`` when the vault refuses it."""
        if self.store.get_session(session_id) is None:
            return False
        await self._credentials.restore(session_id)
        was_open = request_id in self._credentials.pending(session_id)
        saved = await self._credentials.submit(session_id, request_id, value)
        if saved and was_open:
            self._continue_after_connect(session_id, request_id)
        return saved

    def _continue_after_connect(self, session_id: str, request_id: str) -> None:
        """A Connect card that just reported its connection continues its request."""
        from dodaios.agent_chat.credential_requests import CLI, PLUGIN

        try:
            spec = self._credentials.spec(session_id, request_id)
            turn_id = self._credentials.turn_of(session_id, request_id)
        except KeyError:  # the field was forgotten with its chat
            return
        if spec.kind not in (PLUGIN, CLI):
            return
        resume = getattr(self, "_connect_resume", None)
        if resume is None:
            from dodaios.agent_chat.connect_resume import ConnectResume

            resume = self._connect_resume = ConnectResume(self)
        resume.connected(session_id, turn_id, spec.label)

    async def decline_credential(self, session_id: str, request_id: str) -> bool:
        if self.store.get_session(session_id) is None:
            return False
        return await self._credentials.decline(session_id, request_id)

    async def discard_credential_requests(self, session_id: str) -> None:
        await self._credentials.discard_session(session_id)

    def pending_credential_requests(self, session_id: str) -> list[str]:
        credentials: CredentialRequests | None = getattr(self, "_credentials", None)
        return credentials.pending(session_id) if credentials is not None else []
