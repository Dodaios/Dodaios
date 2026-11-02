"""Only the ambient owner prepares Appshot surfaces, outside shortcut arming."""

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.appshot.hotkey import AppshotShortcut


@pytest.mark.parametrize(("enabled", "owns"), [(True, True), (False, True), (True, False)])
async def test_prewarm_is_deferred_and_scoped_to_enabled_primary_instance(
    monkeypatch, enabled, owns
):
    config = SimpleNamespace(
        screen_context=SimpleNamespace(enabled=enabled),
        appshot=SimpleNamespace(hotkey="", region_hotkey="", recording_hotkey="", effect=True),
    )
    monkeypatch.setattr("dodaios.core.config.load_config", lambda: config)
    monkeypatch.setattr(
        "dodaios.core.instance.current_instance", lambda: SimpleNamespace(owns_ambient_duties=owns)
    )
    monkeypatch.setattr("dodaios.cu.indicator.controller.get_indicator_controller", lambda: None)
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def warm(_effect):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    owner = AppshotShortcut(object())
    monkeypatch.setattr(owner, "_warm_surfaces", warm)
    await asyncio.wait_for(owner.reload(), 1)
    if enabled and owns:
        await asyncio.wait_for(entered.wait(), 1)
        assert owner._warm_task is not None and not owner._warm_task.done()
    else:
        assert not entered.is_set() and owner._warm_task is None
    await owner.stop()
    assert stopped.is_set() == (enabled and owns)


async def test_area_press_opens_the_warm_picker_before_the_loop_runs(monkeypatch):
    from dodaios.appshot import picker_host

    opened: list[str] = []
    discarded: list[bool] = []

    class Host:
        def open_now(self):
            opened.append("open")
            return True

        async def discard_opened(self):
            discarded.append(True)

    monkeypatch.setattr(picker_host, "_host", Host())
    owner = AppshotShortcut(object())
    fired: list[str] = []
    monkeypatch.setattr(owner, "_fire_threadsafe", fired.append)
    owner._press("window")
    assert opened == [] and fired == ["window"]
    owner._press("region")  # straight from the listener thread
    assert opened == ["open"] and fired == ["window", "region"]

    async def refused(**_kwargs):
        return SimpleNamespace(ok=False, reason_code="disabled", message="off")

    monkeypatch.setattr("dodaios.appshot.service.take_appshot", refused)
    monkeypatch.setattr(owner, "_publish_refusal", lambda _message: asyncio.sleep(0))
    await owner._take("region")
    assert discarded == [True]  # the refusal closes the picker the press opened
