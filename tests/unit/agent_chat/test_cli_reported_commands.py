from dodaios.agent_chat import typeahead


def test_reported_commands_join_the_slash_list(tmp_path):
    typeahead._CLI_REPORTED.clear()
    typeahead._CLI_REPORTED_ANY.clear()
    typeahead.remember_cli_commands("claude-cli", tmp_path, ["compact", "/review", "bad name!"])
    typeahead.remember_cli_commands(
        "claude-cli", tmp_path, [{"name": "compact", "description": "Shrink"}]
    )
    rows = {
        r["value"]: r
        for q in ("compact", "review")
        for r in typeahead.suggest(runner="claude-cli", cwd=tmp_path, trigger="/", query=q)["items"]
    }
    assert rows["compact"]["hint"] == "Shrink"
    assert "review" in rows and "bad name!" not in rows
    # Name-only report keeps the earlier description.
    typeahead.remember_cli_commands("claude-cli", tmp_path, ["compact"])
    key = ("claude-cli", typeahead._folder_key(tmp_path))
    assert typeahead._CLI_REPORTED[key]["compact"] == "Shrink"
    # Codex is untouched.
    assert typeahead.suggest(runner="codex-cli", cwd=tmp_path, trigger="/")["items"] == []
    typeahead._CLI_REPORTED.clear()
    typeahead._CLI_REPORTED_ANY.clear()
