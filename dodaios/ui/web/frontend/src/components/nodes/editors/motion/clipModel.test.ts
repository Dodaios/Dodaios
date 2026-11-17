import { describe, expect, it } from "vitest";

import { produce } from "../produce";
import {
  addItem,
  captionKey,
  clipDuration,
  copySelection,
  deleteSelection,
  ensureIds,
  findItem,
  insertPiece,
  itemKey,
  moveItem,
  pasteBoard,
  pieceFromMedia,
  poseAt,
  removeSilences,
  sceneKey,
  setKey,
  snapTargets,
  snapTime,
  splitAt,
  trimItemEnd,
  trimItemStart,
  trimSceneEnd,
  trimSceneStart,
} from "./clipModel";
import { readMotionSpec, type MotionSpec } from "./motionModel";

const MEDIA = {
  aaaaaaaaaaaaaaaaaaaaaaaa: {
    kind: "video" as const,
    name: "take.mp4",
    file: "aaaaaaaaaaaaaaaaaaaaaaaa.mp4",
    seconds: 20,
    width: 1080,
    height: 1920,
    audio: true,
  },
  bbbbbbbbbbbbbbbbbbbbbbbb: {
    kind: "audio" as const,
    name: "song.mp3",
    file: "bbbbbbbbbbbbbbbbbbbbbbbb.mp3",
    seconds: 60,
    width: 0,
    height: 0,
    audio: true,
  },
};
const V = "aaaaaaaaaaaaaaaaaaaaaaaa";

function clip(): MotionSpec {
  return readMotionSpec({
    format: "tall",
    media: MEDIA,
    scenes: [
      { id: "v1", type: "video", media: V, seconds: 10 },
      { id: "s1", type: "title", title: "End", seconds: 3 },
    ],
    captions: {
      items: [
        { start: 1, end: 2, text: "one two" },
        { start: 6, end: 7, text: "three four" },
      ],
    },
  });
}

const edit = (spec: MotionSpec, change: (draft: MotionSpec) => void) => produce(spec, change);

describe("the main track", () => {
  it("splits a video piece in its source and keeps the track contiguous", () => {
    const next = edit(clip(), (draft) => void splitAt(draft, new Set(), 4));
    expect(next.scenes.map((s) => [s.id, s.seconds, s.in ?? 0])).toEqual([
      ["v1", 4, 0],
      ["v2", 6, 4],
      ["s1", 3, 0],
    ]);
    expect(clipDuration(next)).toBe(13);
  });

  it("splits at the source time a faster piece reached", () => {
    const fast = edit(clip(), (draft) => {
      draft.scenes[0].speed = 2;
      draft.scenes[0].seconds = 5;
    });
    const next = edit(fast, (draft) => void splitAt(draft, new Set([sceneKey("v1")]), 2));
    expect(next.scenes[1].in).toBe(4);
    expect(next.scenes[1].seconds).toBe(3);
  });

  it("shifts keys into the right half of a split", () => {
    const keyed = edit(clip(), (draft) => {
      draft.scenes[0].keys = [
        { t: 0, zoom: 1 },
        { t: 8, zoom: 1.2 },
      ];
    });
    const next = edit(keyed, (draft) => void splitAt(draft, new Set(), 5));
    // Both halves hold the value the picture had at the cut, so neither jumps.
    expect(next.scenes[0].keys).toEqual([
      { t: 0, zoom: 1 },
      { t: 5, zoom: 1.1367 },
    ]);
    expect(next.scenes[1].keys).toEqual([
      { t: 0, zoom: 1.1367 },
      { t: 3, zoom: 1.2 },
    ]);
  });

  it("trims a piece's start in its source and its end inside the source", () => {
    let next = edit(clip(), (draft) => trimSceneStart(draft, 0, 2));
    expect([next.scenes[0].in, next.scenes[0].seconds]).toEqual([2, 8]);
    next = edit(next, (draft) => trimSceneEnd(draft, 0, 100));
    expect(next.scenes[0].seconds).toBe(18);
    next = edit(next, (draft) => trimSceneStart(draft, 0, -5));
    expect([next.scenes[0].in ?? 0, next.scenes[0].seconds]).toEqual([0, 20]);
  });

  it("closes the gap of a deleted piece and moves the captions up with the speech", () => {
    const withMore = edit(clip(), (draft) => void splitAt(draft, new Set(), 4));
    const next = edit(withMore, (draft) => deleteSelection(draft, new Set([sceneKey("v1")]), false));
    expect(next.scenes.map((s) => s.id)).toEqual(["v2", "s1"]);
    expect(next.captions?.items).toEqual([{ start: 2, end: 3, text: "three four" }]);
  });

  it("cuts silences out of a piece and keeps the rest back to back", () => {
    const next = edit(clip(), (draft) => {
      removeSilences(draft, "v1", [
        [0, 0.5],
        [3, 5],
      ]);
    });
    expect(next.scenes.map((s) => [s.in ?? 0, s.seconds])).toEqual([
      [0.5, 2.5],
      [5, 5],
      [0, 3],
    ]);
    // The caption at 6-7 s moved up by 2.5 s.
    expect(next.captions?.items[1]).toEqual({ start: 3.5, end: 4.5, text: "three four" });
  });

  it("lets the first real piece take the place of a blank new clip", () => {
    const blank = readMotionSpec({ scenes: [{ type: "title" }] });
    const next = edit(blank, (draft) => void insertPiece(draft, 1, pieceFromMedia("v9", V, MEDIA[V])));
    expect(next.scenes.map((s) => s.type)).toEqual(["video"]);
    expect(next.scenes[0].seconds).toBe(20);
  });
});

describe("tracks", () => {
  it("puts an item where it fits and a busy place on a new track", () => {
    let spec = clip();
    let first = "";
    let second = "";
    spec = edit(spec, (draft) => {
      first = addItem(draft, "text", { start: 0, seconds: 3, text: "Hook" });
      second = addItem(draft, "text", { start: 1, seconds: 2, text: "Over" });
    });
    expect(findItem(spec, first)?.trackIndex).toBe(0);
    expect(findItem(spec, second)?.trackIndex).toBe(1);
    const firstTrack = spec.tracks![0].id;
    spec = edit(spec, (draft) => moveItem(draft, second, 4, firstTrack));
    // Free on the first track now; the emptied track is dropped.
    expect(findItem(spec, second)?.trackIndex).toBe(0);
    expect(spec.tracks).toHaveLength(1);
  });

  it("trims a sound in its source and never past its end", () => {
    let id = "";
    let spec = edit(clip(), (draft) => {
      id = addItem(draft, "audio", { start: 0, seconds: 30, media: "bbbbbbbbbbbbbbbbbbbbbbbb" });
    });
    spec = edit(spec, (draft) => trimItemStart(draft, id, 5));
    expect(findItem(spec, id)?.item).toMatchObject({ start: 5, seconds: 25, in: 5 });
    spec = edit(spec, (draft) => trimItemEnd(draft, id, 500));
    expect(findItem(spec, id)?.item.seconds).toBe(55);
  });

  it("ripples a track when asked and leaves it when not", () => {
    let a = "";
    let b = "";
    const spec = edit(clip(), (draft) => {
      a = addItem(draft, "text", { start: 0, seconds: 2, text: "A" });
      b = addItem(draft, "text", { start: 3, seconds: 2, text: "B" });
    });
    expect(findItem(edit(spec, (d) => deleteSelection(d, new Set([itemKey(a)]), true)), b)?.item.start).toBe(1);
    expect(findItem(edit(spec, (d) => deleteSelection(d, new Set([itemKey(a)]), false)), b)?.item.start).toBe(3);
  });

  it("copies and pastes items and captions with fresh ids at the playhead", () => {
    let a = "";
    const spec = edit(clip(), (draft) => {
      a = addItem(draft, "text", { start: 1, seconds: 2, text: "A" });
    });
    const board = copySelection(spec, new Set([itemKey(a), captionKey(0)]));
    let keys: string[] = [];
    const next = edit(spec, (draft) => {
      keys = pasteBoard(draft, board, 10);
    });
    expect(keys).toHaveLength(1);
    expect(findItem(next, keys[0].slice(2))?.item).toMatchObject({ start: 10, text: "A" });
    expect(next.captions?.items.at(-1)).toMatchObject({ start: 10, end: 11, text: "one two" });
  });
});

describe("snapping and keys", () => {
  it("snaps to the playhead and to edges within the tolerance only", () => {
    const targets = snapTargets(clip(), 4.2, new Set());
    expect(snapTime(4.25, targets, 0.1)).toEqual({ t: 4.2, to: 4.2 });
    expect(snapTime(9.95, targets, 0.1)).toEqual({ t: 10, to: 10 });
    expect(snapTime(8, targets, 0.1).to).toBeNull();
  });

  it("eases between keys like the page does", () => {
    const look = {};
    setKey(look, 0, { zoom: 1 });
    setKey(look, 2, { zoom: 2 });
    expect(poseAt(look, 1).zoom).toBeCloseTo(1.5);
    expect(poseAt(look, 3).zoom).toBe(2);
  });

  it("gives every scene and item an id", () => {
    const spec = edit(readMotionSpec({ scenes: [{ type: "title", title: "x" }, { type: "text", text: "y" }] }), ensureIds);
    expect(spec.scenes.map((s) => s.id)).toEqual(["s1", "s2"]);
  });
});
