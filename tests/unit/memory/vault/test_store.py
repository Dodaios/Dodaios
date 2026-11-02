"""Personal memory vault store (ADR-0044)."""

from __future__ import annotations

import pytest

from dodaios.memory.vault import MemoryVault


class Clock:
    def __init__(self) -> None:
        self.value = "2026-01-01T09:00:00+00:00"

    def __call__(self) -> str:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(tmp_path, clock) -> MemoryVault:
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    yield v
    v.close()


def test_remember_then_same_statement_is_not_duplicated(vault):
    first = vault.remember("I live in Hamburg.", "profile", entities=["Hamburg"])
    again = vault.remember("i live in  hamburg", "profile")
    assert first.action == "added"
    assert again.action == "existing"
    assert again.memory.id == first.memory.id
    assert vault.stats()["current"] == 1


def test_supersede_keeps_history_and_answers_both_now_and_before(vault, clock):
    old = vault.remember("I live in Hamburg.", "profile", entities=["Hamburg"]).memory
    clock.value = "2026-06-01T09:00:00+00:00"
    new = vault.supersede(old.id, "I live in Berlin.", entities=["Berlin"]).memory

    current = vault.list()
    assert [m.text for m in current] == ["I live in Berlin."]
    closed = vault.get(old.id)
    assert closed.valid_to == "2026-06-01T09:00:00+00:00"
    assert closed.expired_at is not None
    assert new.supersedes_id == old.id
    assert [m.text for m in vault.history(new.id)] == ["I live in Hamburg.", "I live in Berlin."]
    assert [m.text for m in vault.about("hamburg")] == ["I live in Hamburg."]


def test_invalidate_closes_without_replacement(vault):
    m = vault.remember("I work at Acme.", "profile", entities=["Acme"]).memory
    assert vault.invalidate(m.id, reason="quit")
    assert vault.list() == []
    assert vault.list(include_closed=True)[0].id == m.id
    assert not vault.invalidate(m.id)


def test_forget_purges_every_version_and_blocks_inferred_rewrite(vault):
    old = vault.remember("My ex is called Sam.", "relationship", entities=["Sam"]).memory
    new = vault.supersede(old.id, "My ex Sam moved to Paris.").memory

    assert vault.forget(new.id) == 2
    assert vault.get(old.id) is None and vault.get(new.id) is None
    assert vault.search("Sam") == []
    assert vault.entities() == []
    assert all("Sam" not in str(row["detail"]) for row in vault.audit_log())
    assert len(vault.tombstones()) == 2

    blocked = vault.remember("My ex Sam moved to Paris.", "relationship", origin="inferred")
    assert blocked.action == "blocked"
    # The user saying it again is their choice.
    assert vault.remember("My ex Sam moved to Paris.", "relationship").action == "added"


def test_secrets_are_refused(vault):
    fake_key = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    result = vault.remember(f"My OpenAI key is {fake_key}")
    assert result.action == "refused"
    assert vault.stats()["current"] == 0


def test_ephemeral_memory_expires(vault, clock):
    vault.remember(
        "I have a dentist appointment tomorrow.",
        "ephemeral",
        valid_to="2026-01-02T23:59:59+00:00",
    )
    assert len(vault.list()) == 1
    clock.value = "2026-01-03T00:00:00+00:00"
    assert vault.list() == []
    with pytest.raises(ValueError):
        vault.remember("Something short-lived.", "ephemeral")


def test_search_ranks_entity_matches_and_hides_closed_rows(vault):
    vault.remember("Viktoria is my sister.", "relationship", entities=["Viktoria"])
    vault.remember("I had dinner with friends in San Francisco.", "episode")
    old = vault.remember("My favourite food is sushi.", "preference").memory
    vault.supersede(old.id, "My favourite food is ramen.")

    hits = vault.search("who is viktoria")
    assert hits[0].memory.text == "Viktoria is my sister."
    assert [h.memory.text for h in vault.search("favourite food")] == [
        "My favourite food is ramen."
    ]
    assert len(vault.search("favourite food", include_closed=True)) == 2
    assert vault.search("   ") == []
    assert vault.search('"unbalanced') == []


def test_search_ignores_accents(vault):
    vault.remember("My favourite place is the Café de Flore.", "preference")
    assert vault.search("cafe")[0].memory.text == "My favourite place is the Café de Flore."


def test_profile_block_order_budget_and_exclusions(vault):
    vault.remember("Name: Ruben.", "profile")
    vault.remember("Prefers short answers.", "preference")
    vault.remember("Never send emails without asking.", "procedural")
    vault.remember("Went hiking last Sunday.", "episode")
    vault.remember("Has a chronic illness.", "profile", sensitivity="sensitive")
    vault.remember("Wife is called Lea.", "relationship", pinned=True)

    block = vault.profile_block()
    assert block.index("Pinned:") < block.index("About the user:") < block.index("Preferences:")
    assert "Went hiking" not in block
    assert "chronic" not in block
    assert block.count("Wife is called Lea.") == 1

    small = vault.profile_block(max_chars=40)
    assert len(small) <= 40
    assert small.startswith("Pinned:")


def test_scope_keeps_projects_apart(vault):
    vault.remember("Uses tabs.", "preference", scope="project:a")
    vault.remember("Uses spaces.", "preference", scope="project:b")
    vault.remember("Likes dark mode.", "preference")
    texts = {m.text for m in vault.list(scope="project:a")}
    assert texts == {"Uses tabs.", "Likes dark mode."}


def test_validation(vault):
    with pytest.raises(ValueError):
        vault.remember("", "profile")
    with pytest.raises(ValueError):
        vault.remember("x", "diary")
    with pytest.raises(ValueError):
        vault.remember("x", "profile", origin="robot")
    with pytest.raises(KeyError):
        vault.supersede("mem_missing", "y")


def test_pin_and_usage_counters(vault):
    m = vault.remember("Drinks coffee black.", "preference").memory
    assert vault.pin(m.id)
    vault.mark_used([m.id, m.id])
    got = vault.get(m.id)
    assert got.pinned and got.use_count == 2 and got.last_used_at


def test_reopen_keeps_data(tmp_path, clock):
    path = tmp_path / "vault.db"
    with MemoryVault(path, clock=clock) as v:
        v.remember("Born in 1990.", "profile")
        vault_id = v.vault_id
    with MemoryVault(path, clock=clock) as v:
        assert v.vault_id == vault_id
        assert v.list()[0].text == "Born in 1990."
