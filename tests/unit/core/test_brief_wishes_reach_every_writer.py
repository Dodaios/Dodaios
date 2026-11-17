"""The person's brief wishes reach every place that writes a brief.

The lead's message line is covered in ``test_brief_wishes.py``. Here: the
lead's system prompt (the brain runner has no message line), the voice
composer that writes pane prompts, and the live voice backends.
"""

from __future__ import annotations

import pytest

import dodaios.core.config as core_config
from dodaios.agentic_ide import file_index, prompt_composer
from dodaios.agentic_ide.prompt_blueprint import system_prompt, user_block
from dodaios.agentic_ide.task_kind import KIND_IMPLEMENT, KIND_INVESTIGATE, KIND_REVIEW
from dodaios.brain.manager import BrainManager
from dodaios.core import brief_wishes
from dodaios.core.config import load_config
from dodaios.live.config import LiveConfig

WISH = "I approve every PR myself; open it and stop"


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path)
    return tmp_path


def _manager() -> BrainManager:
    m = BrainManager.__new__(BrainManager)
    m._soul = None
    m._user_profile = None
    m._people = None
    m._core_memory = None
    m._system_prompt_extra = ""
    m._memory_context_suffix = ""
    m._reply_language = "auto"
    m._active_turn_identity = None
    cfg = load_config()
    cfg.performance.cache_optimized_prompt = False
    m._config = cfg
    return m


def test_the_system_prompt_carries_the_wishes_only_when_there_are_some() -> None:
    m = _manager()
    assert "AGENT BRIEF WISHES" not in m._build_system_prompt()
    brief_wishes.save_wishes(WISH)
    prompt = m._build_system_prompt()
    assert "AGENT BRIEF WISHES" in prompt
    assert f"- {WISH}" in prompt


def test_the_voice_composer_ships_a_change_by_default() -> None:
    implement = system_prompt(KIND_IMPLEMENT)
    assert "change ends shipped" in implement
    assert "commit, push and merge" in implement
    assert "No git limits" in implement
    # Work that changes nothing has nothing to ship.
    for kind in (KIND_REVIEW, KIND_INVESTIGATE):
        assert "commit, push and merge" not in system_prompt(kind)


def _block(**extra: object) -> str:
    return user_block(
        utterance="fix the login button",
        instruction="fix the login button",
        terminal_name="T2",
        agent_display="Claude Code",
        profile_lines=[],
        candidates=[],
        skeletons={},
        house_rules="",
        **extra,
    )


def test_the_composer_input_puts_the_wishes_beside_the_request() -> None:
    assert "STANDING WISHES" not in _block()
    block = _block(wishes=WISH)
    assert "THE PERSON'S STANDING WISHES FOR EVERY BRIEF" in block
    assert block.index(WISH) < block.index("WHAT THE USER SAID")


async def test_the_composer_reads_the_stored_wishes(tmp_path, monkeypatch) -> None:
    class _Profile:
        def summary_lines(self) -> list[str]:
            return ["Folder: /work"]

    class _Session:
        folder = str(tmp_path)
        profile = _Profile()

    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    file_index.reset_cache()
    brief_wishes.save_wishes(WISH)
    seen: dict[str, str] = {}

    async def _capture(**kwargs: object) -> str:
        seen["user"] = str(kwargs["user_block"])
        return "## Task\nFix the login button."

    monkeypatch.setattr(prompt_composer, "_resolve_writer", lambda: (object(), "test"))
    monkeypatch.setattr(prompt_composer, "_llm_compose", _capture)
    await prompt_composer.compose("fix the login button", session=_Session(), terminal_name="T2")
    assert WISH in seen["user"]


def test_the_live_voice_backend_hears_the_wishes() -> None:
    def wire() -> str:
        cfg = LiveConfig(configured=True, backend_model="chosen-model")
        return cfg.session_config(language="en", tools=[])["delegation"]["responses"][
            "instructions"
        ]

    assert WISH not in wire()
    brief_wishes.save_wishes(WISH)
    assert f"- {WISH}" in wire()
