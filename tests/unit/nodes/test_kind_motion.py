"""The motion node type: the film spec, its player page and its library card."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Any

import pytest

from dodaios.artifacts.design_guide import THEME_CSS
from dodaios.nodes.kinds import motion
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError
from tests.unit.nodes.editable import check_editable, editable_fields

PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8AAAAMB"
    "AQDJ/pLvAAAAAElFTkSuQmCC"
)
ATTACKS = ("<script>alert(1)</script>", '"><img src=x onerror=alert(1)>')


def _node(spec: dict[str, Any], *, title: str = "Film", language: str = "en") -> Node:
    return Node(
        id="0123456789ab",
        type="motion",
        title=title,
        spec=spec,
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_500,
        language=language,
    )


def _film(*scenes: Any, **top: Any) -> dict[str, Any]:
    return motion.normalize({"scenes": list(scenes), **top})


class _Tags(HTMLParser):
    """Collects every start tag with its attributes, and the text of scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        self._in_script = tag == "script"

    def handle_endtag(self, tag: str) -> None:
        self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts.append(data)


def _tags(page: str) -> _Tags:
    parser = _Tags()
    parser.feed(page)
    parser.close()
    return parser


_EDIT_MARKS = re.compile(r' data-(?:at|src)="[^"]*"')


def _drawn(page: str) -> str:
    """What the page DRAWS: its body without the edit marks. Those carry the
    stored strings as escaped attributes, which are data and never drawn."""
    body = page.index("<body")
    return _EDIT_MARKS.sub("", page[body : page.index("<script>", body)])


# ---------------------------------------------------------------- normalize


def test_normalize_fills_the_defaults_and_is_idempotent() -> None:
    spec = motion.normalize({"scenes": [{"title": "Hello", "junk": 1}], "junk": True})

    assert spec == {
        "format": "wide",
        "theme": "dark",
        "accent": "",
        "loop": False,
        "scenes": [{"type": "title", "title": "Hello", "seconds": 4.0, "transition": "fade"}],
    }
    assert motion.normalize(spec) == spec


def test_normalize_is_idempotent_for_every_scene_type() -> None:
    spec = _film(
        {"type": "title", "kicker": "K", "title": "T", "text": "X"},
        {"type": "text", "text": "One statement that is set large."},
        {"type": "bullets", "title": "Points", "bullets": ["a", "b", "c"]},
        {"type": "stat", "value": 42, "unit": "%", "label": "share", "detail": "of all"},
        {"type": "bars", "title": "B", "items": [{"label": "x", "value": "3.5"}], "unit": "k"},
        {"type": "quote", "quote": "Said so.", "by": "Someone"},
        {"type": "steps", "title": "How", "steps": [{"title": "One", "text": "first"}, "Two"]},
        {"type": "image", "image": PNG, "caption": "A picture"},
        {"type": "end", "title": "Bye", "text": "See you", "transition": "zoom", "seconds": 3},
        format="tall",
        theme="light",
        accent="Green",
        loop="true",
    )

    assert [scene["type"] for scene in spec["scenes"]] == list(motion.SCENE_TYPES)
    assert spec["format"] == "tall" and spec["theme"] == "light"
    assert spec["accent"] == "green" and spec["loop"] is True
    assert spec["scenes"][3]["value"] == "42"
    assert spec["scenes"][4]["items"] == [{"label": "x", "value": 3.5}]
    assert spec["scenes"][6]["steps"][1] == {"title": "Two", "text": ""}
    assert motion.normalize(spec) == spec
    assert motion.normalize(json.loads(json.dumps(spec))) == spec


@pytest.mark.parametrize(
    ("scene", "expected"),
    [
        ({"title": "Opening", "text": "A line under it"}, "title"),
        ({"text": "Only a statement"}, "text"),
        ({"title": "Points", "bullets": ["one", "two"]}, "bullets"),
        ({"value": "38 %", "label": "share"}, "stat"),
        ({"title": "By region", "items": [{"label": "North", "value": 4}]}, "bars"),
        ({"quote": "It works.", "by": "A reader"}, "quote"),
        ({"title": "How", "steps": [{"title": "Ask"}]}, "steps"),
        ({"image": PNG, "caption": "The library"}, "image"),
        ({"type": "nonsense", "quote": "Unknown types fall back to the fields."}, "quote"),
        ("A bare string is a statement", "text"),
    ],
)
def test_scene_type_is_inferred_from_the_fields(scene: Any, expected: str) -> None:
    assert _film(scene)["scenes"][0]["type"] == expected


def test_only_the_fields_a_scene_type_uses_are_kept() -> None:
    scene = _film(
        {
            "type": "quote",
            "quote": "Kept",
            "by": "Kept too",
            "title": "dropped",
            "bullets": ["dropped"],
            "value": 3,
            "items": [{"label": "dropped", "value": 1}],
        }
    )["scenes"][0]

    assert scene == {
        "type": "quote",
        "quote": "Kept",
        "by": "Kept too",
        "seconds": scene["seconds"],
        "transition": "fade",
    }


def test_lists_are_capped_and_texts_are_clipped() -> None:
    spec = _film(
        {"type": "bullets", "bullets": [f"point {n}" for n in range(9)] + ["", None]},
        {"type": "bars", "items": [{"label": f"L{n}", "value": n} for n in range(12)]},
        {"type": "steps", "steps": [{"title": f"S{n}"} for n in range(9)]},
        {"type": "title", "title": "t" * 500, "kicker": "k" * 500, "text": "x" * 900},
        *[{"text": f"scene {n}"} for n in range(60)],
    )

    bullets, bars, steps, title = spec["scenes"][:4]
    assert len(spec["scenes"]) == motion.MAX_SCENES
    assert len(bullets["bullets"]) == motion.MAX_BULLETS
    assert len(bars["items"]) == motion.MAX_ITEMS
    assert len(steps["steps"]) == motion.MAX_STEPS
    assert (len(title["title"]), len(title["kicker"]), len(title["text"])) == (120, 60, 280)


def test_seconds_transition_format_and_accent_stay_in_bounds() -> None:
    spec = _film(
        {"text": "short", "seconds": 0.2, "transition": "spin"},
        {"text": "long", "seconds": 400, "transition": "CUT"},
        {"text": "exact", "seconds": "2.26"},
        {"text": "default", "seconds": "soon"},
        format="cinema",
        theme="neon",
        accent="red;background:url(x)",
    )

    seconds = [scene["seconds"] for scene in spec["scenes"]]
    assert seconds[:3] == [motion.MIN_SECONDS, motion.MAX_SECONDS, 2.3]
    assert 3.0 <= seconds[3] <= 5.0
    assert [scene["transition"] for scene in spec["scenes"][:2]] == ["fade", "cut"]
    assert (spec["format"], spec["theme"], spec["accent"]) == ("wide", "dark", "")
    assert _film({"text": "x"}, accent="#1a2b3c")["accent"] == "#1a2b3c"
    assert _film({"text": "x"}, accent="#12345")["accent"] == ""


def test_default_seconds_follow_the_content() -> None:
    few = _film({"bullets": ["a"]})["scenes"][0]["seconds"]
    many = _film({"bullets": ["a", "b", "c", "d", "e"]})["scenes"][0]["seconds"]

    assert 3.0 <= few < many <= 6.0


def test_total_duration_is_the_sum_of_the_scenes() -> None:
    spec = _film(
        {"title": "One", "seconds": 2.5},
        {"text": "Two", "seconds": 3.2},
        {"type": "end", "title": "Three", "seconds": 4},
    )
    page = motion.render(_node(spec))

    assert motion.preview(spec)["seconds"] == 9.7
    assert 'aria-valuemax="9.7"' in page
    assert [attrs["data-sec"] for tag, attrs in _tags(page).tags if tag == "section"] == [
        "2.5",
        "3.2",
        "4.0",
    ]
    # One tick per scene boundary: after 2.5 s and after 5.7 s of 9.7 s.
    assert page.count('class="f-tick"') == 2
    assert 'style="left:25.773%"' in page and 'style="left:58.763%"' in page


@pytest.mark.parametrize(
    ("spec", "needle"),
    [
        (None, "'scenes'"),
        ("a film please", "'scenes'"),
        ({"scenes": []}, "'scenes'"),
        ({"scenes": "none"}, "'scenes'"),
        ({"scenes": [42]}, "Scene 1 must be an object"),
        ({"scenes": [{"title": "ok"}, {"seconds": 3}]}, "Scene 2 has nothing to show"),
        ({"scenes": [{"type": "bars", "items": [{"label": "x", "value": "many"}]}]}, "'items'"),
        ({"scenes": [{"type": "bullets", "title": "No points"}]}, "'bullets'"),
        ({"scenes": [{"type": "stat", "label": "no number"}]}, "'value'"),
        ({"scenes": [{"type": "image", "image": "https://example.org/a.png"}]}, "data:image"),
        ({"scenes": [{"type": "steps", "steps": [{}]}]}, "'steps'"),
    ],
)
def test_an_unusable_spec_is_refused_with_one_sentence(spec: Any, needle: str) -> None:
    with pytest.raises(NodeError) as raised:
        motion.normalize(spec)

    message = str(raised.value)
    assert needle in message
    assert message.endswith(".") and "\n" not in message


# ------------------------------------------------------------------- render


def _attacked(attack: str) -> dict[str, Any]:
    return _film(
        {"type": "title", "kicker": attack, "title": attack, "text": attack},
        {"type": "text", "kicker": attack, "text": attack},
        {"type": "bullets", "kicker": attack, "title": attack, "bullets": [attack, attack]},
        {"type": "stat", "kicker": attack, "value": attack, "unit": attack, "label": attack,
         "detail": attack},
        {"type": "stat", "value": f"{attack[:8]}1,5{attack[:8]}", "unit": attack},
        {"type": "bars", "kicker": attack, "title": attack, "unit": attack,
         "items": [{"label": attack, "value": 3}]},
        {"type": "quote", "quote": attack, "by": attack},
        {"type": "steps", "kicker": attack, "title": attack,
         "steps": [{"title": attack, "text": attack}]},
        {"type": "image", "image": PNG, "caption": attack},
        {"type": "end", "kicker": attack, "title": attack, "text": attack},
        accent=attack,
        format=attack,
        theme=attack,
    )  # fmt: skip


@pytest.mark.parametrize("attack", ATTACKS)
def test_no_text_from_a_spec_reaches_the_page_unescaped(attack: str) -> None:
    page = motion.render(_node(_attacked(attack), title=attack, language=attack))
    parsed = _tags(page)

    assert "<script>alert" not in page
    assert "<img src=x" not in page
    assert '"><img src=x' not in page
    # The page's own scripts are the theme stamp and the player, nothing else.
    assert [tag for tag, _ in parsed.tags].count("script") == 3
    assert not any("alert(1)" in script for script in parsed.scripts)
    assert not any(name.startswith("on") for _, attrs in parsed.tags for name in attrs)
    pictures = [attrs for tag, attrs in parsed.tags if tag == "img"]
    assert [picture["src"] for picture in pictures] == [PNG]
    assert pictures[0]["alt"] == attack
    # The words are still there, as text, not only in the edit marks.
    assert "&lt;" in _drawn(page)


def test_an_image_that_is_not_embedded_never_becomes_a_source() -> None:
    with pytest.raises(NodeError):
        _film({"image": "javascript:alert(1)", "type": "image"})
    spec = _film({"title": "Kept", "image": "https://example.org/track.png"})

    assert "image" not in spec["scenes"][0]
    assert "example.org" not in motion.render(_node(spec))


def test_render_is_deterministic_and_carries_no_network_reference() -> None:
    spec = _film(*motion.EXAMPLE["scenes"], accent="blue")
    page = motion.render(_node(spec))

    assert page == motion.render(_node(json.loads(json.dumps(spec))))
    assert page.startswith("<!doctype html>")
    for needle in ("http://", "https://", "//cdn", "@import", "url("):
        assert needle not in page


def test_the_page_is_a_film_player_with_labelled_controls() -> None:
    page = motion.render(_node(_film({"title": "One"}, {"text": "Two"}, loop=True)))
    parsed = _tags(page)
    labels = {attrs.get("aria-label") for _, attrs in parsed.tags}
    buttons = [attrs for tag, attrs in parsed.tags if tag == "button"]

    assert '<body class="fill">' in page
    assert {"Play", "Restart", "Loop", "Replay", "Position", "Playback"} <= labels
    assert len(buttons) == 4 and all(button.get("aria-label") for button in buttons)
    assert all(button.get("type") == "button" for button in buttons)
    assert 'data-loop="1"' in page and 'aria-pressed="true"' in page
    assert 'role="slider"' in page and 'tabindex="0"' in page
    # The film handles its own pointer and keys; the kit's page script stays out.
    assert "dodaios-open-link" not in page
    assert "requestAnimationFrame" in page
    assert "prefers-reduced-motion" in parsed.scripts[-1]
    assert '"autoplay"' in parsed.scripts[-1] and 'q.get("t")' in parsed.scripts[-1]


def test_the_film_moves_by_script_not_by_css_animation() -> None:
    # The shared stylesheet switches CSS animations off under reduced motion,
    # and a film must be the same frame for the same time.
    assert "@keyframes" not in motion._FILM_CSS
    assert "animation" not in motion._FILM_CSS
    page = motion.render(_node(_film({"title": "Two words"})))

    cues = [attrs for _, attrs in _tags(page).tags if "a-word" in (attrs.get("class") or "")]
    assert [cue["data-s"] for cue in cues] == ["0.20", "0.28"]
    assert all(float(cue["data-d"]) > 0 for cue in cues)


def test_each_format_has_its_stage_and_the_film_its_own_theme() -> None:
    wide = motion.render(_node(_film({"title": "W"})))
    tall = motion.render(_node(_film({"title": "T"}, format="tall", theme="light")))

    assert 'data-w="1280" data-h="720"' in wide and 'data-tone="dark"' in wide
    assert 'data-w="720" data-h="1280"' in tall and 'data-tone="light"' in tall
    # Both scopes come from the shared tokens, whatever the app's theme is.
    dark = motion._tokens(':root[data-theme="dark"]')
    assert "--bg:#141413" in dark and dark in THEME_CSS
    assert f'.film-fit[data-tone="dark"]{{{dark}}}' in wide
    assert '.film-fit[data-tone="light"]{color-scheme:light;' in wide


def test_the_accent_is_a_token_or_the_specs_own_color() -> None:
    default = motion.render(_node(_film({"title": "A"})))
    named = motion.render(_node(_film({"title": "A"}, accent="green")))
    custom = motion.render(_node(_film({"title": "A"}, accent="#FFD400")))

    assert 'style="--fa:var(--accent);--fa-ink:var(--bg)"' in default
    assert 'style="--fa:var(--s3);--fa-ink:var(--bg)"' in named
    # A light accent takes dark text on it, a dark accent light text.
    assert 'style="--fa:#FFD400;--fa-ink:#141413"' in custom
    assert motion._ink_on("#123") == "#FDFDFC"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1,240", ("", "1,240", "", 1240.0, 0, ",", ".")),
        ("1.240,5", ("", "1.240,5", "", 1240.5, 1, ".", ",")),
        ("38 %", ("", "38", " %", 38.0, 0, "", ".")),
        ("0.125", ("", "0.125", "", 0.125, 3, "", ".")),
        ("3,5", ("", "3,5", "", 3.5, 1, "", ",")),
        ("€2.4M", ("€", "2.4", "M", 2.4, 1, "", ".")),
        ("10 000", ("", "10 000", "", 10000.0, 0, " ", ".")),
        ("-7", ("-", "7", "", 7.0, 0, "", ".")),
    ],
)
def test_a_stat_counts_up_to_the_number_in_its_value(
    value: str, expected: tuple[str, str, str, float, int, str, str]
) -> None:
    assert motion._counted(value) == expected


@pytest.mark.parametrize("value", ["24/7", "3 of 5", "soon", "1,24,0", "v2.0.1"])
def test_a_value_that_is_not_one_number_is_shown_as_it_is(value: str) -> None:
    assert motion._counted(value) is None
    page = motion.render(_node(_film({"value": value})))

    assert "data-to=" not in page


def test_bars_grow_to_their_share_of_the_largest_value() -> None:
    spec = _film(
        {"title": "T", "unit": "%", "items": [
            {"label": "a", "value": 50}, {"label": "b", "value": 12.5},
            {"label": "c", "value": -25},
        ]}
    )  # fmt: skip
    page = motion.render(_node(spec))

    assert [f"--v:{share}" in page for share in ("100.00", "25.00", "50.00")] == [True] * 3
    assert 'data-to="12.5000" data-dec="1" data-intl' in page
    assert 'data-to="-25.0000" data-dec="0" data-intl' in page


def test_steps_light_up_in_order_and_avoid_the_kits_class_names() -> None:
    steps = {"title": "How", "steps": [{"title": "A"}, {"title": "B"}, {"title": "C"}]}
    wide = motion.render(_node(_film(steps)))
    tall = motion.render(_node(_film(steps, format="tall")))
    lit = [
        float(attrs["data-s"])
        for _, attrs in _tags(wide).tags
        if "a-lit" in (attrs.get("class") or "")
    ]

    assert len(lit) == 3 and lit == sorted(lit) and lit[0] < lit[1] < lit[2]
    # "col" and "row" belong to the shared kit (its column chart).
    assert 'class="f-steps is-row"' in wide and 'class="f-steps is-stack"' in tall


# ------------------------------------------------- preview, starter, guide


def test_preview_has_exactly_the_cards_values() -> None:
    spec = _film(
        {"type": "title", "kicker": "K", "title": "T" * 100, "text": "S" * 200},
        {"text": "later", "seconds": 2.25},
        format="square",
        theme="light",
        accent="violet",
    )
    card = motion.preview(spec)

    assert set(card) == {"title", "subtitle", "seconds", "dark", "accent", "format"}
    assert card["title"] == "T" * 60 and card["subtitle"] == "S" * 80
    assert card["seconds"] == 6.2 and isinstance(card["seconds"], float)
    assert card["dark"] is False and card["accent"] == "var(--s5)"
    assert card["format"] == "square"


def test_preview_reads_the_first_scene_that_says_something() -> None:
    card = motion.preview(_film({"image": PNG}, {"value": "42", "label": "answers"}))

    assert (card["title"], card["subtitle"]) == ("42", "answers")
    assert card["dark"] is True and card["accent"] == ""
    assert motion.preview({})["seconds"] == 0.0


def test_starter_is_a_three_scene_film_around_the_title() -> None:
    spec = motion.starter("Quarterly <review>", "en")

    assert [scene["type"] for scene in spec["scenes"]] == ["title", "bullets", "end"]
    assert spec["scenes"][0]["title"] == "Quarterly <review>"
    assert motion.normalize(spec) == spec
    assert "<review>" not in motion.render(_node(spec))
    assert motion.starter("", "en")["scenes"][0]["title"]


def test_guide_is_compact_and_its_example_is_a_valid_spec() -> None:
    spec = motion.normalize(motion.EXAMPLE)

    assert motion.normalize(spec) == spec
    assert json.dumps(motion.EXAMPLE, ensure_ascii=False, separators=(",", ":")) in motion.GUIDE
    assert len(motion.GUIDE) <= 2_500
    assert all(name in motion.GUIDE for name in motion.SCENE_TYPES)
    assert motion.render(_node(spec)).count('<section class="scene') == 4


def test_a_bare_decimal_is_written_the_readers_way() -> None:
    scene = {"type": "stat", "value": 99.9, "unit": "%", "label": "x"}
    spec = motion.normalize({"scenes": [scene]})
    german = motion.render(_node(spec, language="de"))
    english = motion.render(_node(spec, language="en"))

    assert ">99,9<" in german
    assert ">99.9<" in english
    # A value the model wrote out keeps its own marks in every language.
    written = motion.normalize({"scenes": [{"type": "stat", "value": "1,240", "label": "x"}]})
    assert ">1,240<" in motion.render(_node(written, language="de"))


# ------------------------------------------------------------------ editing


def _every_type() -> dict[str, Any]:
    return _film(
        {"type": "title", "kicker": "K", "title": "Two words", "text": "X"},
        {"type": "text", "kicker": "Say", "text": "One statement that is set large."},
        {"type": "bullets", "kicker": "B", "title": "Points", "bullets": ["a", "b", "c"]},
        {"type": "stat", "kicker": "S", "value": 42, "unit": "%", "label": "share",
         "detail": "of all"},
        {"type": "bars", "kicker": "R", "title": "B", "unit": "k",
         "items": [{"label": "x", "value": "3.5"}, {"label": "y", "value": 1240}]},
        {"type": "quote", "quote": "Said so, plainly.", "by": "Someone"},
        {"type": "steps", "kicker": "How", "title": "How",
         "steps": [{"title": "One", "text": "first"}, "Two"]},
        {"type": "image", "image": PNG, "caption": "A picture"},
        {"type": "end", "kicker": "Bye", "title": "Bye", "text": "See you"},
    )  # fmt: skip


@pytest.mark.parametrize(
    "spec",
    [
        motion.normalize(motion.EXAMPLE),
        motion.starter("Quarterly review", "en"),
        _every_type(),
        _every_type() | {"format": "tall"},
    ],
    ids=["example", "starter", "every-type", "every-type-tall"],
)
def test_every_text_offered_for_editing_is_the_value_the_spec_holds(spec: dict[str, Any]) -> None:
    for language in ("en", "de"):
        page = motion.render(_node(spec, language=language))
        fields = check_editable(page, spec, "Film")

        assert fields
        assert [at for at, n in Counter(field.at for field in fields).items() if n > 1] == []
        # One line each: Enter saves, and the app never has to draw the film again.
        assert not any(field.multiline or field.refresh for field in fields)


def test_the_paths_of_a_small_film_are_exactly_its_texts() -> None:
    spec = _film(
        {"type": "title", "kicker": "K", "title": "Two words", "text": "Under"},
        {"type": "stat", "value": 42, "unit": "%", "label": "share"},
        {"type": "bars", "title": "B", "unit": "k",
         "items": [{"label": "x", "value": 3.5}, {"label": "y", "value": 2}]},
        {"type": "steps", "steps": [{"title": "Ask", "text": ""}, {"title": "Do", "text": "it"}]},
    )  # fmt: skip
    fields = check_editable(motion.render(_node(spec)), spec, "Film")

    # The bars' unit is drawn after every value, so it is no one place to write
    # into; a step's empty text is not drawn at all.
    assert {field.at for field in fields} == {
        "/scenes/0/kicker",
        "/scenes/0/title",
        "/scenes/0/text",
        "/scenes/1/value",
        "/scenes/1/unit",
        "/scenes/1/label",
        "/scenes/2/title",
        "/scenes/2/items/0/label",
        "/scenes/2/items/0/value",
        "/scenes/2/items/1/label",
        "/scenes/2/items/1/value",
        "/scenes/3/steps/0/title",
        "/scenes/3/steps/1/title",
        "/scenes/3/steps/1/text",
    }
    assert len(fields) == 14


def test_split_texts_carry_the_stored_string_and_bar_values_are_numbers() -> None:
    spec = _every_type()
    fields = {field.at: field for field in editable_fields(motion.render(_node(spec)))}

    # Drawn as words that rise one by one; edited as the stored string.
    for at, value in (
        ("/scenes/0/title", "Two words"),
        ("/scenes/1/text", "One statement that is set large."),
        ("/scenes/5/quote", "Said so, plainly."),
        ("/scenes/8/title", "Bye"),
    ):
        assert fields[at].src == value and fields[at].text == value
    # A number is stored as text; the count is drawn inside the field.
    assert spec["scenes"][3]["value"] == "42" and fields["/scenes/3/value"].src == "42"
    # A bar's value is a number, edited plainly, drawn in the reader's notation.
    assert spec["scenes"][4]["items"] == [
        {"label": "x", "value": 3.5},
        {"label": "y", "value": 1240},
    ]
    for at, src in (("/scenes/4/items/0/value", "3.5"), ("/scenes/4/items/1/value", "1240")):
        assert (fields[at].kind, fields[at].src) == ("number", src)
    # A plain text is the field itself, without a source of its own.
    assert fields["/scenes/2/bullets/1"].src is None and fields["/scenes/2/bullets/1"].text == "b"


def test_a_localized_stat_is_edited_as_stored() -> None:
    spec = motion.normalize({"scenes": [{"type": "stat", "value": 99.9, "unit": "%"}]})
    page = motion.render(_node(spec, language="de"))
    field = {field.at: field for field in check_editable(page, spec, "Film")}["/scenes/0/value"]

    assert (field.text, field.src) == ("99,9", "99.9")


def test_a_hostile_text_is_only_ever_an_escaped_attribute_or_text() -> None:
    attack = ATTACKS[1]
    spec = _attacked(attack)
    page = motion.render(_node(spec))
    fields = check_editable(page, spec, "Film")

    assert any(field.src == attack for field in fields)
    assert f'data-src="{html.escape(attack, quote=True)}"' in page
    assert attack not in page


def test_the_film_stands_while_it_is_edited() -> None:
    script = _tags(motion.render(_node(_every_type()))).scripts[-1]

    # The mode is watched on <html>, also when it was set before the script ran.
    assert "MutationObserver" in script and '"data-node-mode"' in script
    assert script.rstrip().endswith("moded();\n})();")
    assert 'getAttribute("data-node-mode")==="edit"' in script
    # Play is off, every move lands on a settled scene, the stage click is inert.
    assert "if(playing||editing)return;" in script
    assert "if(editing)t=settled(index(t));" in script
    assert "if(editing||e.target.closest" in script
    # A saved text is split, counted and sized again in the page, not redrawn.
    assert '"node-field-saved"' in script
    for name in ("split(el,v)", "recount(el,v)", "restat(el,v)", "refit(box)"):
        assert name in script
