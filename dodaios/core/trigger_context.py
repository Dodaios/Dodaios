"""Trusted execution ancestry, separate from externally supplied payloads."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

current_trigger_path: ContextVar[tuple[str, ...]] = ContextVar("current_trigger_path", default=())

#: True while work the person started THEMSELVES runs — "Run now" on a task,
#: routine or workflow. The default (False) means unattended: a schedule, a
#: trigger, a webhook or any other background start. asyncio tasks copy the
#: context when they are created, so a run spawned inside the block keeps it.
current_started_by_user: ContextVar[bool] = ContextVar("current_started_by_user", default=False)


@contextmanager
def started_by_user() -> Iterator[None]:
    """Mark the work started inside this block as started by the person."""
    token = current_started_by_user.set(True)
    try:
        yield
    finally:
        current_started_by_user.reset(token)


class CapacityDeferred(RuntimeError):
    """Unattended work found nothing it may bill and was skipped, not run.

    ``code`` names the reason in a stable, machine-readable word a UI puts in
    its own (translated) words: ``"api_key_seat"`` when the run's own seat
    bills a per-token key while a subscription is connected; ``""`` for the
    generic "no subscription or local model was free". ``provider`` is the seat
    the code refers to, when there is one. The message stays the readable
    English sentence for logs and ``last_error``.
    """

    def __init__(self, *args: object, code: str = "", provider: str = "") -> None:
        super().__init__(*args)
        self.code = code
        self.provider = provider


class RoutineDeferred(RuntimeError):
    """Admission succeeded, but the owning agent has not started any side effect."""
