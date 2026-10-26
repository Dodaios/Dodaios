"""``GET /api/self-build/noticed``: what the loop counts so far, for the page."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core.config import SelfBuildConfig
from dodaios.self_build import Kind, SelfBuild
from dodaios.self_build.miner import Miner, Observation
from dodaios.self_build.signals import SignalStore

DAY = 86_400_000


def _client(tmp_path: Path, store: SignalStore | None) -> tuple[TestClient, SelfBuild]:
    from dodaios.ui.web.self_build_routes import router

    cfg = SimpleNamespace(self_build=SelfBuildConfig(silent_days=7))
    svc = SelfBuild(tmp_path, lambda: cfg)
    app = FastAPI()
    app.state.self_build = svc
    app.state.config = cfg
    app.state.self_build_signals = store
    app.include_router(router)
    return TestClient(app), svc


def _ask(miner: Miner, text: str, ts: int, tools: tuple[str, ...] = ()) -> None:
    obs = Observation(text=text, channel="chat", conversation=f"c{ts}", ts_ms=ts, tools=tools)
    miner.observe(obs)


def test_noticed_lists_repeats_with_progress_and_counts_one_offs(tmp_path: Path) -> None:
    import time

    now = int(time.time() * 1000)
    store = SignalStore(tmp_path / "signals.db")
    miner = Miner(store)
    mail = "@gmail did I get any important emails today"
    for day in (3, 2, 1):
        _ask(miner, mail, now - day * DAY, tools=("mcp:gmail/search",))
    _ask(miner, "what is on my calendar tomorrow morning", now - 2 * DAY)
    _ask(miner, "what is on my calendar tomorrow morning", now - DAY)
    _ask(miner, "translate this sentence into french please", now - DAY)

    client, svc = _client(tmp_path, store)
    body = client.get("/api/self-build/noticed").json()

    assert body["threshold"] == {"times": 3, "days": 3, "window_days": 28}
    assert body["quiet_start"]["days"] == 7
    assert body["quiet_start"]["until_ms"] - body["quiet_start"]["since_ms"] == 7 * DAY
    assert body["once"] == 1
    labels = [n["label"] for n in body["needs"]]
    assert labels == [
        "did I get any important emails today",
        "what is on my calendar tomorrow morning",
    ]
    first, second = body["needs"]
    assert (first["times"], first["days"], first["stage"]) == (3, 3, "ready")
    assert (second["times"], second["days"], second["stage"]) == (2, 2, "counting")

    # A need that became a proposal points at it; a live build drops off the list.
    sig = store.cluster(first["id"]).signature
    record = svc.ledger.open_case(Kind.SKILL, sig, "Check important mail")
    proposed = client.get("/api/self-build/noticed").json()["needs"][0]
    assert (proposed["stage"], proposed["build_id"]) == ("proposed", record.id)
    store.close()
    svc.ledger.close()


def test_noticed_is_empty_without_the_signal_store(tmp_path: Path) -> None:
    client, svc = _client(tmp_path, None)
    body = client.get("/api/self-build/noticed").json()
    assert body["needs"] == [] and body["once"] == 0
    svc.ledger.close()
