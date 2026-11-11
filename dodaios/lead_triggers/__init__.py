"""Events from the person's world as input for the lead, with a two-stage filter.

See ``docs/lead-event-triggers.md``.
"""

from .event import SOURCES, TriggerEvent, normalize
from .service import TriggerService
from .settings import Policy, SourceRule, TriggerSettings

__all__ = [
    "SOURCES",
    "Policy",
    "SourceRule",
    "TriggerEvent",
    "TriggerService",
    "TriggerSettings",
    "normalize",
]
