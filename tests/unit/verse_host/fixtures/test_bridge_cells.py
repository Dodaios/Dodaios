"""cells.bin/1 golden vectors: byte layout, round trip, and malformed frames (G0.11)."""

from __future__ import annotations

import struct

import pytest

from scripts.unreal import bridge_cells as bc
from scripts.unreal import bridge_schema

VECTORS = bridge_schema.read_json(bridge_schema.DATA_DIR / "cells" / "vectors.json")
VALID = {v["name"]: v for v in VECTORS["valid"]}


def test_header_of_the_contract_example_by_offset() -> None:
    # bridge-protocol.md 5.4, read with plain struct offsets, not the codec.
    blob = bytes.fromhex(VALID["contract_delta"]["bin_hex"])
    assert blob[0:2] == b"VC"
    assert blob[2] == 1 and blob[3] == 2  # version, kind delta
    assert struct.unpack_from("<H", blob, 4) == (1,)  # ref
    assert struct.unpack_from("<II", blob, 6) == (91, 88)  # seq, base
    assert struct.unpack_from("<HH", blob, 14) == (132, 40)  # cols, rows
    assert struct.unpack_from("<hh", blob, 18) == (39, 2)  # cursor
    assert struct.unpack_from("<H", blob, 22) == (1,)  # row records
    assert struct.unpack_from("<HH", blob, 24) == (38, 2)  # row 38, two runs
    col, cells, fg, bg, attrs, text_bytes = struct.unpack_from("<HHIIHH", blob, 28)
    assert (col, cells, attrs) == (0, 14, 1)  # bold
    assert fg == (2 << 24) | 0x4FB86A and bg == 0
    text = "✔ tests passed".encode()
    assert text_bytes == len(text) == 16
    assert blob[44 : 44 + text_bytes] == text
    col, cells, fg, bg, attrs, text_bytes = struct.unpack_from("<HHIIHH", blob, 44 + 16)
    assert (col, cells, fg, bg, attrs, text_bytes) == (14, 5, (1 << 24) | 8, 0, 0, 5)
    assert len(blob) == 44 + 16 + 16 + 5


@pytest.mark.parametrize("name", sorted(VALID))
def test_vector_round_trips_byte_exact(name: str) -> None:
    vec = VALID[name]
    frame, blob = vec["frame"], bytes.fromhex(vec["bin_hex"])
    assert (
        bc.encode(frame["data"], ref=vec["ref"], seq=frame["seq"], base=frame.get("base")) == blob
    )
    decoded = bc.decode(blob)
    assert decoded["rows_changed"] == bc.normalise_runs(frame["data"]["rows_changed"])
    assert (decoded["seq"], decoded["ref"], decoded["kind"]) == (
        frame["seq"],
        vec["ref"],
        frame["data"]["kind"],
    )
    assert bc.encode(decoded, ref=decoded["ref"], seq=decoded["seq"], base=decoded["base"]) == blob


@pytest.mark.parametrize("vec", VECTORS["invalid"], ids=lambda v: v["name"])
def test_malformed_vector_is_rejected(vec: dict) -> None:
    with pytest.raises(bc.CellsError):
        bc.decode(bytes.fromhex(vec["bin_hex"]))


def test_vectors_cover_the_cell_model() -> None:
    attrs, fg_modes, wide, kinds = set(), set(), False, set()
    for vec in VECTORS["valid"]:
        kinds.add(vec["frame"]["data"]["kind"])
        for row in vec["frame"]["data"]["rows_changed"]:
            for run in row["runs"]:
                attrs.update(run["attrs"])
                for colour in (run["fg"], run["bg"]):
                    fg_modes.add(bc.colour_to_u32(colour) >> 24)
                wide = wide or "wide" in run["attrs"]
    assert attrs == set(bc.ATTRS)
    assert fg_modes == {0, 1, 2}
    assert wide and kinds == {"snapshot", "delta"}
    hidden = VALID["snapshot_empty_hidden_cursor"]["frame"]["data"]
    assert hidden["cursor"] == [-1, -1] and hidden["cols"] == 240 and hidden["rows"] == 60


def test_colour_and_attribute_encodings() -> None:
    assert bc.colour_to_u32(None) == 0
    assert bc.colour_to_u32({"i": 9}) == 0x01000009
    assert bc.colour_to_u32("#e3242b") == 0x02E3242B
    assert bc.colour_from_u32(0x02E3242B) == "#e3242b"
    assert bc.attrs_to_u16(["bold", "wide"]) == 0b1_0000_0001
    assert bc.attrs_from_u16(0b1_0001_0000) == ["inverse", "wide"]
    for bad in ({"i": 256}, "#E3242B", "red", {"i": 1, "x": 2}):
        with pytest.raises(bc.CellsError):
            bc.colour_to_u32(bad)
    with pytest.raises(bc.CellsError):
        bc.attrs_from_u16(1 << 9)


def test_grapheme_clusters_and_spans() -> None:
    assert bc.graphemes("café") == ["c", "a", "f", "é"]
    assert len(bc.graphemes("\U0001f9d1‍\U0001f527")) == 1
    assert bc.run_span({"text": "漢字", "attrs": ["wide"]}) == 4
    vec = VALID["grapheme_clusters"]
    run = vec["frame"]["data"]["rows_changed"][0]["runs"][0]
    assert len(run["text"].encode()) == 6 and len(bc.graphemes(run["text"])) == 4


def test_encoder_refuses_rows_outside_the_grid() -> None:
    data = dict(VALID["contract_delta"]["frame"]["data"])
    data["rows"] = 61
    with pytest.raises(bc.CellsError):
        bc.encode(data, ref=1, seq=2, base=1)
    with pytest.raises(bc.CellsError):
        bc.encode(VALID["contract_delta"]["frame"]["data"], ref=1, seq=2, base=None)
