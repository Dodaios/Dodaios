"""Moved to :mod:`dodaios.memory.secret_guard` (ADR-0044); kept until the wiki is removed."""

from dodaios.memory.secret_guard import *  # noqa: F403
from dodaios.memory.secret_guard import contains_secret, find_secrets

__all__ = ["contains_secret", "find_secrets"]
