"""Credential broker: handles in, values only inside the executor (see broker.py)."""

from .backends import (
    BackendError,
    BackendStatus,
    BitwardenBackend,
    CredentialBackend,
    HandleInfo,
    LocalVaultBackend,
    OnePasswordBackend,
    Secrets,
)
from .broker import BrowserLogins, CredentialBroker, SiteRules, broker_for, redact_active
from .handles import Handle, find_handles, parse_handle

__all__ = [
    "BackendError",
    "BackendStatus",
    "BitwardenBackend",
    "BrowserLogins",
    "CredentialBackend",
    "CredentialBroker",
    "Handle",
    "HandleInfo",
    "LocalVaultBackend",
    "OnePasswordBackend",
    "Secrets",
    "SiteRules",
    "broker_for",
    "find_handles",
    "parse_handle",
    "redact_active",
]
