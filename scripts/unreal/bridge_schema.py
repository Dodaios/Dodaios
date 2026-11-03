#!/usr/bin/env python3
"""Schema validator and fixture check for ``verse.bridge/1`` (G0.11).

The golden data lives in ``unreal/Verse/Tests/Data/bridge/`` (read by the
Unreal automation tests) and is mirrored byte for byte, line endings aside,
into ``tests/unit/verse_host/fixtures/bridge/`` (read by the backend pytest).
Both sides check against the same ``verse.bridge.1.schema.json``.

    python scripts/unreal/bridge_schema.py              # check every fixture and the mirror
    python scripts/unreal/bridge_schema.py --sync       # copy the Unreal tree to the mirror
    python scripts/unreal/bridge_schema.py FRAME.json   # validate frames in a file

Layout of the data folder:

``verse.bridge.1.schema.json``
    JSON Schema (2020-12). ``x-messages`` lists every message type with its
    direction, kind, topic and the ``$defs`` of its frame, data and reply.
``messages/<type>.json``
    Golden frames of one type; the first is the contract's own example.
``replies/<command>.json``
    ``[{request, reply}]`` pairs, success and error answers.
``cells/vectors.json``
    ``cells.bin/1`` vectors: a ``screens.frame`` in ``cells.json/1`` form and
    its exact bytes, plus malformed frames a decoder must reject.
``scenarios/<name>.json``
    Scripted runs ``scripts/unreal/fake_bridge.py`` serves.
"""

from __future__ import annotations

import argparse
import functools
import json
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from scripts.unreal import bridge_cells  # noqa: E402

DATA_DIR = REPO_ROOT / "unreal" / "Verse" / "Tests" / "Data" / "bridge"
MIRROR_DIR = REPO_ROOT / "tests" / "unit" / "verse_host" / "fixtures" / "bridge"
SCHEMA_FILE = "verse.bridge.1.schema.json"
PROTOCOL = "verse.bridge/1"

TO_SERVER = "verse_to_server"
TO_VERSE = "server_to_verse"

#: Keywords whose failures a live reader tolerates (unknown fields, unknown
#: enum values with a documented fallback). Golden data tolerates none.
_LENIENT_KEYWORDS = {"additionalProperties", "enum"}


class Schema:
    """The loaded ``verse.bridge/1`` schema with one validator per ``$defs`` entry."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.messages: dict[str, dict] = document["x-messages"]
        self._defs = document["$defs"]
        self._validators: dict[str, Draft202012Validator] = {}

    # -------------------------------------------------------------- catalogue

    def entry(self, type_: str) -> dict | None:
        return self.messages.get(type_)

    def commands(self) -> list[str]:
        return sorted(t for t, e in self.messages.items() if e["kind"] == "command")

    def topic_of(self, type_: str) -> str | None:
        entry = self.messages.get(type_)
        return entry.get("topic") if entry else None

    def is_delta(self, type_: str, data: Any = None) -> bool:
        """Whether a frame of ``type_`` carries ``base`` (a screens snapshot does not)."""
        entry = self.messages.get(type_) or {}
        if not entry.get("delta"):
            return False
        if type_ == "screens.frame":
            return isinstance(data, dict) and data.get("kind") == "delta"
        return True

    # -------------------------------------------------------------- validation

    def _validator(self, pointer: str) -> Draft202012Validator:
        name = pointer.removeprefix("#/$defs/")
        if name not in self._validators:
            if name not in self._defs:
                raise KeyError(f"schema has no $defs entry {name!r}")
            sub = {"$defs": self._defs, "$ref": f"#/$defs/{name}"}
            self._validators[name] = Draft202012Validator(sub)
        return self._validators[name]

    def _errors(self, pointer: str, value: Any, where: str, lenient: bool) -> list[str]:
        out = []
        for error in self._validator(pointer).iter_errors(value):
            if lenient and _tolerated(error):
                continue
            path = "/".join(str(p) for p in error.absolute_path)
            out.append(f"{where}{'/' + path if path else ''}: {error.message}")
        return out

    def validate_frame(self, frame: Any, *, lenient: bool = False) -> list[str]:
        """Every problem with one JSON frame, as readable strings (empty: valid).

        ``lenient`` accepts unknown fields and unknown values of enums that
        name an ``x-fallback``, as a live reader must (contract section 2).
        """
        if not isinstance(frame, dict):
            return ["frame is not a JSON object"]
        type_ = frame.get("type")
        entry = self.messages.get(type_) if isinstance(type_, str) else None
        if entry is None:
            return [f"unknown message type {type_!r}"]
        data = frame.get("data")
        if type_ == "screens.frame" and not self.is_delta(type_, data):
            frame_def = "#/$defs/frame.server_to_verse"
        else:
            frame_def = entry["frame"]
        errors = self._errors(frame_def, frame, type_, lenient=False)
        errors += self._errors(entry["data"], data, f"{type_}.data", lenient)
        if "base" in frame and "seq" in frame and isinstance(frame["base"], int):
            if isinstance(frame["seq"], int) and frame["base"] >= frame["seq"]:
                errors.append(f"{type_}: base {frame['base']} is not below seq {frame['seq']}")
        if type_ == "screens.frame" and isinstance(data, dict) and not errors:
            try:
                bridge_cells.check_rows(data["cols"], data["rows"], data["rows_changed"])
            except bridge_cells.CellsError as exc:
                errors.append(f"screens.frame.data: {exc}")
        return errors

    def validate_reply(self, reply: dict, command: str, *, lenient: bool = False) -> list[str]:
        """A reply frame, and its ``result`` against the command's result schema."""
        errors = self.validate_frame(reply, lenient=lenient)
        entry = self.messages.get(command)
        if entry is None or entry["kind"] != "command":
            return errors + [f"{command!r} is not a command"]
        data = reply.get("data") if isinstance(reply, dict) else None
        if isinstance(data, dict) and data.get("ok") is True:
            errors += self._errors(
                entry["result"], data.get("result"), f"{command} result", lenient
            )
        return errors

    def validate_scenario(self, scenario: Any) -> list[str]:
        """A fake-bridge scenario: shape, and every frame and reply it would serve."""
        if not isinstance(scenario, dict):
            return ["scenario is not a JSON object"]
        errors = []
        name = scenario.get("name", "?")
        keys = {
            "name",
            "description",
            "topics",
            "watch_screens",
            "watch_chat_tails",
            "state",
            "replies",
            "steps",
        }
        if set(scenario) != keys:
            errors.append(f"{name}: keys must be exactly {sorted(keys)}")
            return errors
        for topic in scenario["topics"]:
            if topic not in self.document["x-subscribed-topics"]:
                errors.append(f"{name}: {topic!r} is not a subscribable topic")
        for type_, data in scenario["state"].items():
            if not type_.endswith(".snapshot"):
                errors.append(f"{name}: state key {type_!r} is not a snapshot type")
                continue
            errors += self.validate_frame(_wrap(type_, data, 1), lenient=False)
        for command, answers in scenario["replies"].items():
            for i, data in enumerate(answers):
                reply = {"type": "reply", "seq": 2, "ts": 0.0, "re": "c-1", "data": data}
                errors += [
                    f"{name}: replies.{command}[{i}]: {e}"
                    for e in self.validate_reply(reply, command)
                ]
        last = 0
        for i, step in enumerate(scenario["steps"]):
            where = f"{name}: steps[{i}]"
            at = step.get("at_ms")
            if not isinstance(at, int) or at < last:
                errors.append(f"{where}: at_ms must be an integer not below the previous step's")
            else:
                last = at
            if "frame" in step:
                allowed = {"at_ms", "frame", "lenient", "note"}
                frame = step["frame"]
                if not isinstance(frame, dict) or set(frame) != {"type", "data"}:
                    errors.append(f"{where}: a step frame holds only type and data")
                    continue
                entry = self.messages.get(frame["type"])
                if (
                    entry is None
                    or entry["dir"] != TO_VERSE
                    or entry["kind"] in {"reply", "handshake"}
                ):
                    errors.append(f"{where}: {frame['type']!r} is not a server feed or event")
                    continue
                base = 1 if self.is_delta(frame["type"], frame["data"]) else None
                wrapped = _wrap(frame["type"], frame["data"], 2, base=base)
                errors += [
                    f"{where}: {e}"
                    for e in self.validate_frame(wrapped, lenient=bool(step.get("lenient")))
                ]
                if step.get("lenient") and not self.validate_frame(wrapped):
                    errors.append(f"{where}: marked lenient but valid as golden data")
            elif "expect" in step:
                allowed = {"at_ms", "expect", "timeout_ms", "optional", "note"}
                expect = step["expect"]
                entry = self.messages.get(expect.get("type"))
                if entry is None or entry["dir"] != TO_SERVER:
                    errors.append(f"{where}: expects {expect.get('type')!r}, not a Verse message")
                if not isinstance(step.get("timeout_ms"), int) or step["timeout_ms"] <= 0:
                    errors.append(f"{where}: expect needs a positive timeout_ms")
            else:
                errors.append(f"{where}: a step has a frame or an expect")
                continue
            if set(step) - allowed:
                errors.append(f"{where}: unknown keys {sorted(set(step) - allowed)}")
        return errors


def _tolerated(error: Any) -> bool:
    if error.validator not in _LENIENT_KEYWORDS:
        return False
    return error.validator == "additionalProperties" or "x-fallback" in error.schema


def _wrap(type_: str, data: Any, seq: int, *, base: int | None = None) -> dict:
    frame = {"type": type_, "seq": seq, "ts": 0.0, "data": data}
    if base is not None:
        frame["base"] = base
    return frame


@functools.lru_cache(maxsize=4)
def load(data_dir: Path = DATA_DIR) -> Schema:
    return Schema(read_json(data_dir / SCHEMA_FILE))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def data_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


# ------------------------------------------------------------------ fixture check


def check_messages(schema: Schema, root: Path) -> list[str]:
    errors = []
    seen = set()
    for path in sorted((root / "messages").glob("*.json")):
        type_ = path.stem
        frames = read_json(path)
        if not isinstance(frames, list) or not frames:
            errors.append(f"messages/{path.name}: not a non-empty list")
            continue
        for i, frame in enumerate(frames):
            if frame.get("type") != type_:
                errors.append(
                    f"messages/{path.name}[{i}]: type {frame.get('type')!r} in the {type_} file"
                )
            errors += [f"messages/{path.name}[{i}]: {e}" for e in schema.validate_frame(frame)]
        seen.add(type_)
    for type_ in sorted(set(schema.messages) - seen):
        errors.append(f"messages/{type_}.json: no golden frame for a catalogued type")
    return errors


def check_replies(schema: Schema, root: Path) -> list[str]:
    errors = []
    seen = set()
    for path in sorted((root / "replies").glob("*.json")):
        command = path.stem
        pairs = read_json(path)
        if schema.entry(command) is None or schema.entry(command)["kind"] != "command":
            errors.append(f"replies/{path.name}: {command!r} is not a command")
            continue
        ok_seen = False
        for i, pair in enumerate(pairs):
            where = f"replies/{path.name}[{i}]"
            request, reply = pair.get("request"), pair.get("reply")
            if set(pair) - {"request_invalid"} != {"request", "reply"}:
                errors.append(f"{where}: a pair holds request, reply, request_invalid")
                continue
            if request.get("type") != command:
                errors.append(f"{where}: request type {request.get('type')!r}")
            request_errors = schema.validate_frame(request)
            if pair.get("request_invalid"):
                # A malformed request the server answers with bad_request.
                if not request_errors:
                    errors.append(f"{where}: request_invalid but the request is valid")
                if reply.get("data", {}).get("error", {}).get("code") != "bad_request":
                    errors.append(f"{where}: an invalid request is answered with bad_request")
            else:
                errors += [f"{where} request: {e}" for e in request_errors]
            errors += [f"{where} reply: {e}" for e in schema.validate_reply(reply, command)]
            if reply.get("re") != request.get("id"):
                errors.append(f"{where}: re {reply.get('re')!r} is not id {request.get('id')!r}")
            ok_seen = ok_seen or reply.get("data", {}).get("ok") is True
        if not ok_seen:
            errors.append(f"replies/{path.name}: no successful reply")
        seen.add(command)
    for command in sorted(set(schema.commands()) - seen):
        errors.append(f"replies/{command}.json: no request/reply pair for a command")
    return errors


def check_cells(schema: Schema, root: Path) -> list[str]:
    errors = []
    vectors = read_json(root / "cells" / "vectors.json")
    if vectors.get("format") != "cells.bin/1":
        errors.append("cells/vectors.json: format is not cells.bin/1")
    for vec in vectors.get("valid", []):
        where = f"cells/{vec.get('name')}"
        frame = vec["frame"]
        errors += [f"{where}: {e}" for e in schema.validate_frame(frame)]
        data = frame["data"]
        blob = bytes.fromhex(vec["bin_hex"])
        try:
            encoded = bridge_cells.encode(
                data, ref=vec["ref"], seq=frame["seq"], base=frame.get("base")
            )
            decoded = bridge_cells.decode(blob)
        except bridge_cells.CellsError as exc:
            errors.append(f"{where}: {exc}")
            continue
        if encoded != blob:
            errors.append(f"{where}: encoding the JSON frame does not give bin_hex")
        expect = {
            "kind": data["kind"],
            "ref": vec["ref"],
            "seq": frame["seq"],
            "base": frame.get("base"),
            "cols": data["cols"],
            "rows": data["rows"],
            "cursor": data["cursor"],
            "rows_changed": bridge_cells.normalise_runs(data["rows_changed"]),
        }
        if decoded != expect:
            errors.append(f"{where}: decoding bin_hex does not give the JSON frame")
        if data["kind"] == "snapshot" and data.get("ref") != vec["ref"]:
            errors.append(
                f"{where}: snapshot ref {data.get('ref')} differs from the vector ref {vec['ref']}"
            )
    for vec in vectors.get("invalid", []):
        try:
            bridge_cells.decode(bytes.fromhex(vec["bin_hex"]))
        except bridge_cells.CellsError:
            continue
        errors.append(f"cells/{vec.get('name')}: malformed vector decodes without an error")
    return errors


def check_scenarios(schema: Schema, root: Path) -> list[str]:
    errors = []
    for path in sorted((root / "scenarios").glob("*.json")):
        scenario = read_json(path)
        if scenario.get("name") != path.stem:
            errors.append(
                f"scenarios/{path.name}: name {scenario.get('name')!r} differs from the file name"
            )
        errors += [f"scenarios/{e}" for e in schema.validate_scenario(scenario)]
    return errors


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def check_mirror(root: Path = DATA_DIR, mirror: Path = MIRROR_DIR) -> list[str]:
    """The pytest mirror holds exactly the Unreal tree's files (line endings aside)."""
    ours = {p.relative_to(root).as_posix(): p for p in data_files(root)}
    theirs = (
        {p.relative_to(mirror).as_posix(): p for p in data_files(mirror)} if mirror.is_dir() else {}
    )
    errors = [f"mirror misses {rel}" for rel in sorted(set(ours) - set(theirs))]
    errors += [f"mirror has extra {rel}" for rel in sorted(set(theirs) - set(ours))]
    for rel in sorted(set(ours) & set(theirs)):
        if _normalised(ours[rel]) != _normalised(theirs[rel]):
            errors.append(f"mirror differs: {rel}")
    if errors:
        errors.append("run: python scripts/unreal/bridge_schema.py --sync")
    return errors


def check_all(root: Path = DATA_DIR, *, mirror: Path | None = MIRROR_DIR) -> list[str]:
    schema = Schema(read_json(root / SCHEMA_FILE))
    errors = check_messages(schema, root) + check_replies(schema, root)
    errors += check_cells(schema, root) + check_scenarios(schema, root)
    if mirror is not None:
        errors += check_mirror(root, mirror)
    return errors


def sync(root: Path = DATA_DIR, mirror: Path = MIRROR_DIR) -> int:
    if mirror.exists():
        shutil.rmtree(mirror)
    count = 0
    for path in data_files(root):
        target = mirror / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_normalised(path))
        count += 1
    return count


def _frames_in(paths: Iterable[str]) -> Iterable[tuple[str, Any]]:
    for name in paths:
        value = read_json(Path(name))
        for i, frame in enumerate(value if isinstance(value, list) else [value]):
            yield f"{name}[{i}]", frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="JSON files holding one frame or a list of frames")
    parser.add_argument(
        "--sync", action="store_true", help="copy the Unreal tree to the pytest mirror"
    )
    parser.add_argument(
        "--lenient", action="store_true", help="validate files as a live reader would"
    )
    args = parser.parse_args(argv)
    if args.sync:
        print(f"synced {sync()} files to {MIRROR_DIR.relative_to(REPO_ROOT).as_posix()}")
        return 0
    if args.files:
        schema = load()
        errors = [
            f"{where}: {e}"
            for where, f in _frames_in(args.files)
            for e in schema.validate_frame(f, lenient=args.lenient)
        ]
    else:
        errors = check_all()
    for error in errors:
        print(error)
    print("bridge fixtures: OK" if not errors else f"bridge fixtures: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
