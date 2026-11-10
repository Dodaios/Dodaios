"""A provider that refused the last call is not the first one tried again."""

from __future__ import annotations

from types import SimpleNamespace

from dodaios.brain import provider_health_ledger as ledger
from dodaios.realtime import factory
from dodaios.speech import provider_refusal as pr


class _Plugin:
    supports_realtime = True
    implicit_usage_fallback_allowed = True
    provider_fallback_allowed = True


def test_configured_order_demotes_a_recently_refused_provider(monkeypatch) -> None:
    plugins = {"dead": _Plugin, "alive": _Plugin}
    monkeypatch.setattr(factory, "list_plugins", lambda _group: list(plugins))
    monkeypatch.setattr(factory, "load", lambda _group, name, protocol=None: plugins[name])
    store = ledger.ProviderHealthLedger(None)
    ledger.set_ledger(store)
    try:
        cfg = SimpleNamespace(brain=SimpleNamespace(realtime=SimpleNamespace(
            provider="dead", fallback_provider="alive", fallback_provider_2=None,
        )))
        assert factory._configured_provider_ids(cfg) == ["dead", "alive"]
        pr.remember("dead", pr.refusal_of_kind(pr.KIND_BUSY))
        assert factory._configured_provider_ids(cfg) == ["alive", "dead"]
        pr.remember("dead", pr.refusal_of_kind(pr.KIND_CREDIT))
        assert factory._configured_provider_ids(cfg) == ["alive"]
    finally:
        ledger.set_ledger(None)
