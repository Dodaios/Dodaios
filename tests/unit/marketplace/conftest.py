"""Isolate the process-wide CapabilityRegistry for marketplace tests.

Constructing an ``MCPToolAdapter`` (which ``PluginToolRegistry`` does, via the
fake client) registers a ``Capability`` into the global singleton registry.
Without isolation those registrations leak into later test modules — notably
the routing suite, whose intent resolution iterates the whole registry — and
make the suite order-dependent. Snapshot + restore around every test here.
"""
import pytest

from dodaios.core.capabilities import get_registry


@pytest.fixture(autouse=True)
def _forget_community_index_state():
    """The index reader keeps the parsed feed, the last failure and a
    background task in module state; none of it may cross into the next test."""
    from dodaios.marketplace import community_source

    community_source.reset_runtime_state()
    yield
    community_source.reset_runtime_state()


@pytest.fixture(autouse=True)
def _isolate_capability_registry():
    reg = get_registry()
    with reg._lock:  # noqa: SLF001 — test-only snapshot of the singleton
        snapshot = dict(reg._caps)  # noqa: SLF001
    try:
        yield
    finally:
        with reg._lock:  # noqa: SLF001
            reg._caps.clear()  # noqa: SLF001
            reg._caps.update(snapshot)  # noqa: SLF001
