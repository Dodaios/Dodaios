"""Every test starts with no memory refresh remembered as sent (runner_cli)."""

import pytest


@pytest.fixture(autouse=True)
def _no_refresh_sent():
    from dodaios.agent_chat import runner_cli

    runner_cli._REFRESH_SENT.clear()  # noqa: SLF001
    yield
    runner_cli._REFRESH_SENT.clear()  # noqa: SLF001
