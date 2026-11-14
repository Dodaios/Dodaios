"""M5 navigation oracle regressions (offline, no GUI, no billable calls).

Covers the OPR-20261114-01 failure: the goal asks to open example.com,
click "Learn more" and finish on the destination page. The oracle must:

* confirm the full source->link->destination chain (M5 evidence);
* keep rejecting premature finish (still on the source);
* keep rejecting wrong destinations and navigation failures;
* stay not-applicable for unrelated goals (no generic shortcut).
"""

from dodaios.cu.navigation_oracle import (
    destination_evidence,
    history_shows_link_click,
    is_m5_navigation_goal,
    navigation_oracle_verdict,
)

M5_GOAL = (
    "Open Chrome and navigate to example.com. Then click the 'Learn more' "
    "link on the Example Domain page. Finish once the destination page is shown."
)

M5_HISTORY_OK = [
    "step 1: click_element('Nova guia') -> OK",
    "step 2: type('example.com') -> OK",
    "step 5: click_element('Learn more') -> OK (role=Hyperlink rect=(950,700,120,24))",
]

M5_DEST_LABELS = ["Example Domains", "IANA", "Help", "Learn more about Example Domains"]
M5_DEST_TITLE = "Example Domains - IANA"
M5_DEST_FIELD = '"Address and search bar" currently contains "https://iana.org/help/example-domains"'


def test_m5_goal_detected() -> None:
    assert is_m5_navigation_goal(M5_GOAL) is True


def test_non_navigation_goal_not_applicable() -> None:
    assert is_m5_navigation_goal("Open notepad and type hello") is False
    applicable, done, _ = navigation_oracle_verdict(
        "Open notepad and type hello", M5_HISTORY_OK, M5_DEST_LABELS, M5_DEST_TITLE,
    )
    assert (applicable, done) == (False, False)


def test_m5_full_chain_confirms_destination() -> None:
    applicable, done, proof = navigation_oracle_verdict(
        M5_GOAL, M5_HISTORY_OK, M5_DEST_LABELS, M5_DEST_TITLE, M5_DEST_FIELD,
    )
    assert applicable is True
    assert done is True
    assert "iana.org/help/example-domains" in proof
    assert "Learn more" in proof


def test_m5_premature_finish_still_on_source_rejected() -> None:
    history: list[str] = []
    labels = ["Example Domain", "Learn more"]
    title = "Example Domain"
    applicable, done, reason = navigation_oracle_verdict(
        M5_GOAL, history, labels, title,
    )
    assert applicable is True
    assert done is False
    assert "still on the" in reason


def test_m5_wrong_destination_rejected() -> None:
    labels = ["Some other site", "Welcome"]
    title = "Some other site"
    applicable, done, _ = navigation_oracle_verdict(
        M5_GOAL, M5_HISTORY_OK, labels, title,
    )
    assert applicable is True
    assert done is False


def test_m5_link_never_clicked_rejected_even_on_destination_cues() -> None:
    applicable, done, reason = navigation_oracle_verdict(
        M5_GOAL, [], M5_DEST_LABELS, M5_DEST_TITLE,
    )
    assert applicable is True
    assert done is False
    assert "no observed click" in reason


def test_m5_spoofed_single_cue_rejected() -> None:
    # Host cue without content cue (or vice versa) is not verifiable.
    assert destination_evidence(["iana", "random"], "random page", "") == ""
    assert destination_evidence(["Example Domains"], "random page", "") == ""


def test_m5_title_spoof_without_url_rejected() -> None:
    # Title mentions IANA and content cues are present, but the address bar
    # does not show iana.org: weak evidence only, never confirms arrival.
    from dodaios.cu.navigation_oracle import has_weak_destination_cues

    labels = ["Example Domains", "IANA", "Help"]
    title = "Example Domains - IANA"
    assert destination_evidence(labels, title, "") == ""
    assert has_weak_destination_cues(labels, title, "") is True
    applicable, done, reason = navigation_oracle_verdict(
        M5_GOAL, M5_HISTORY_OK, labels, title, "",
    )
    assert applicable is True
    assert done is False
    assert "iana.org" in reason


def test_m5_strong_host_in_labels_confirms() -> None:
    # When the address bar is exposed through clickable labels, that also
    # counts as verifiable host evidence.
    labels = ["Example Domains", "IANA", "https://iana.org/help/example-domains"]
    applicable, done, _ = navigation_oracle_verdict(
        M5_GOAL, M5_HISTORY_OK, labels, M5_DEST_TITLE, "",
    )
    assert (applicable, done) == (True, True)


def test_history_matcher_requires_ok() -> None:
    assert history_shows_link_click(M5_HISTORY_OK) is True
    assert history_shows_link_click(["step 5: click_element('Learn more') -> FAILED"]) is False
    assert history_shows_link_click(["step 5: click_element('Learn more') REFUSED"]) is False
