"""The path-addressed vault model behind the Memory section.

Pure tests: pages are handed in as ``SourcePage`` values, nothing touches
disk. They pin the behaviours the old slug-addressed routes got wrong.
"""

from __future__ import annotations

from dodaios.memory.wiki.vault_model import (
    AgentInfo,
    SourcePage,
    build_model,
    is_empty_body,
    read_properties,
)


def _page(path: str, body: str, **properties: object) -> SourcePage:
    return SourcePage(
        path=path,
        body=body,
        properties=properties,
        page_type=str(properties.get("type", "")),
        mtime=1_000.0,
        size=len(body),
    )


def _notebook(agent_id: str, text: str = "") -> list[SourcePage]:
    entry = (
        f'<!-- memory-entry: {{"id": "{agent_id}1", "importance": 5}} -->\n{text}\n' if text else ""
    )
    return [
        _page(f"society/{agent_id}/MEMORY.md", f"\n{entry}", type="society"),
        _page(f"society/{agent_id}/USER.md", "\n", type="society"),
    ]


def test_files_with_the_same_name_stay_separate_pages() -> None:
    model = build_model(
        [
            *_notebook("ada", "Ada remembers the deploy steps."),
            *_notebook("vega", "Vega knows SQL."),
        ],
        {"vega": AgentInfo("vega", "Vega", "active")},
    )

    assert set(model.pages) == {
        "society/ada/MEMORY.md",
        "society/ada/USER.md",
        "society/vega/MEMORY.md",
        "society/vega/USER.md",
    }
    vega = model.pages["society/vega/MEMORY.md"]
    assert vega.title == "Vega · Memory"
    assert vega.kind == "memory"
    assert vega.summary == "Vega knows SQL."
    assert model.agents["vega"].state == "active"
    # An agent the roster does not know is an orphan, named after its folder.
    assert model.agents["ada"].state == "orphan"
    assert model.pages["society/ada/MEMORY.md"].title == "Ada · Memory"


def test_frontmatter_only_pages_and_skeletons_count_as_empty() -> None:
    assert is_empty_body("")
    assert is_empty_body("\n<!-- memory-entry: {} -->\n")
    assert is_empty_body("# Ruben\n\n## Summary\n\n## Facts\n- \n---\n")
    assert not is_empty_body("# Ruben\n\nPrefers short answers.")

    model = build_model(_notebook("ada"))
    assert model.pages["society/ada/MEMORY.md"].empty
    stats = model.stats()
    assert stats["empty_pages"] == 2
    assert stats["content_pages"] == 0


def test_links_resolve_by_path_name_and_alias_and_report_broken_ones() -> None:
    model = build_model(
        [
            _page(
                "entities/ruben.md",
                "# Ruben\n\nWorks on [[projects/magenta-ide]] and [[Dodaios]].",
                type="entity",
                aliases=["the user"],
            ),
            _page(
                "projects/magenta-ide.md", "# Magenta IDE\n\nBy [[the user|Ruben]].", type="project"
            ),
            _page(
                "entities/dodaios.md", "# Dodaios\n\nAn agent OS.", type="entity", title="Dodaios"
            ),
            _page("projects/other.md", "# Other\n\nSee [[nowhere]].", type="project"),
        ]
    )

    links = model.page_links("entities/ruben.md")
    assert {item["path"] for item in links["outgoing"]} == {
        "projects/magenta-ide.md",
        "entities/dodaios.md",
    }
    assert [item["path"] for item in links["backlinks"]] == ["projects/magenta-ide.md"]
    broken = model.page_links("projects/other.md")["outgoing"]
    assert broken == [
        {"path": None, "title": "nowhere", "kind": None, "broken": True, "raw": "nowhere"}
    ]
    assert model.stats()["broken_links"] == 1


def test_short_links_prefer_the_page_in_the_same_folder() -> None:
    model = build_model(
        [
            _page("entities/bugatti-divo.md", "# Bugatti Divo (car)\n\nA car.", type="entity"),
            _page(
                "projects/bugatti-divo.md", "# Bugatti Divo build\n\nA model kit.", type="project"
            ),
            _page("projects/garage.md", "# Garage\n\nNext up: [[bugatti-divo]].", type="project"),
        ]
    )
    assert model.resolve("bugatti-divo", "projects/garage.md") == "projects/bugatti-divo.md"


def test_plain_text_mentions_link_distinctive_names_only() -> None:
    model = build_model(
        [
            _page("entities/ruben.md", "# Ruben\n\nThe owner.", type="entity"),
            _page("entities/memory.md", "# Memory\n\nA concept page.", type="entity"),
            _page("entities/san-francisco.md", "# San Francisco\n\nA city.", type="entity"),
            *_notebook("ada", "Ruben moved to san francisco; memory is cheap."),
        ]
    )

    mentions = model.page_links("society/ada/MEMORY.md")["mentions"]
    # "Ruben" as written and the multi-word city in any case; the plain
    # word "memory" does not pull in the page titled "Memory".
    assert {item["path"] for item in mentions} == {
        "entities/ruben.md",
        "entities/san-francisco.md",
    }
    mentioned_in = model.page_links("entities/ruben.md")["mentioned_in"]
    assert [item["path"] for item in mentioned_in] == ["society/ada/MEMORY.md"]


def test_system_pages_never_count_as_links_or_map_nodes() -> None:
    model = build_model(
        [
            _page("log.md", "- pages touched: [[entities/ruben]]\n" * 50),
            _page("memory.md", "# My Memory\n\n- [[entities/ruben]]", type="meta"),
            _page("entities/ruben.md", "# Ruben\n\nThe owner.", type="entity"),
        ]
    )
    assert model.stats()["links"] == 0
    assert model.page_links("entities/ruben.md")["backlinks"] == []
    assert [node["id"] for node in model.graph()["nodes"]] == ["entities/ruben.md"]


def test_related_pages_share_a_neighbour() -> None:
    model = build_model(
        [
            _page("entities/a.md", "# A\n\nKnows [[hub]].", type="entity"),
            _page("entities/b.md", "# B\n\nAlso knows [[hub]].", type="entity"),
            _page("entities/hub.md", "# Hub\n\nThe centre.", type="entity"),
        ]
    )
    related = model.related("entities/a.md")
    assert [item["path"] for item in related] == ["entities/b.md"]
    assert related[0]["via"]["path"] == "entities/hub.md"


def test_rewrite_links_keeps_form_alias_and_anchor() -> None:
    model = build_model(
        [
            _page("entities/old-name.md", "# Old name\n\nA page.", type="entity"),
            _page(
                "projects/p.md",
                "# P\n\n[[old-name]], [[entities/old-name|label]], [[old-name#Facts]], [[other]]",
                type="project",
            ),
        ]
    )
    body, count = model.rewrite_links("projects/p.md", "entities/old-name.md", "entities/new-name")
    assert count == 3
    assert "[[new-name]]" in body
    assert "[[entities/new-name|label]]" in body
    assert "[[new-name#Facts]]" in body
    assert "[[other]]" in body


def test_read_properties_keeps_yaml_lists() -> None:
    raw = "---\ntype: entity\naliases:\n- the user\n- Ruben\ncreated: 2026-10-02\n---\n# Ruben\n"
    properties = read_properties(raw)
    assert properties["aliases"] == ["the user", "Ruben"]
    assert properties["created"] == "2026-10-02"
    assert read_properties("# no frontmatter") == {}
    # Broken YAML falls back to flat key/value pairs instead of failing.
    assert read_properties("---\ntitle: a: b: [\nslug: x\n---\n")["slug"] == "x"
