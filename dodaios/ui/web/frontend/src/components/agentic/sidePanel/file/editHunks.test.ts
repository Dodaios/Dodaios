import { describe, expect, it } from "vitest";

import type { DiffFile } from "@/components/agentchat/toolDiff";
import { UNPLACED_HUNK_HEADER, editHunks } from "./editHunks";

const edit = (lines: DiffFile["lines"]): DiffFile => ({
  path: "a.py", lines, added: 0, removed: 0, created: false, truncated: 0,
});

describe("editHunks", () => {
  it("numbers an edit by where its lines sit in the file now", () => {
    const text = "a\nb\nNEW\nd\n";
    const [hunk] = editHunks(edit([
      { kind: "ctx", text: "b" }, { kind: "del", text: "OLD" }, { kind: "add", text: "NEW" }, { kind: "ctx", text: "d" },
    ]), text);
    expect(hunk.header).toBe("@@ -2,3 +2,3 @@");
    expect(hunk.lines.map((line) => [line.kind, line.old_no, line.new_no])).toEqual([
      ["ctx", 2, 2], ["del", 3, null], ["add", null, 3], ["ctx", 4, 4],
    ]);
  });

  it("carries the shift of an earlier hunk into the old numbers below it", () => {
    const text = "x\nadded1\nadded2\ny\nz\nw\n";
    const hunks = editHunks(edit([
      { kind: "ctx", text: "x" }, { kind: "add", text: "added1" }, { kind: "add", text: "added2" },
      { kind: "gap", text: "1" },
      { kind: "ctx", text: "z" }, { kind: "del", text: "gone" }, { kind: "ctx", text: "w" },
    ]), text);
    expect(hunks[1].header).toBe("@@ -3,3 +5,2 @@");
    expect(hunks[1].lines[1]).toMatchObject({ kind: "del", old_no: 4, new_no: null });
  });

  it("draws the edit without numbers when the file no longer holds it", () => {
    const [hunk] = editHunks(edit([{ kind: "add", text: "missing" }]), "other\n");
    expect(hunk.header).toBe(UNPLACED_HUNK_HEADER);
    expect(hunk.lines[0]).toMatchObject({ old_no: null, new_no: null });
    expect(editHunks(edit([{ kind: "add", text: "missing" }]), null)[0].header).toBe(UNPLACED_HUNK_HEADER);
  });

  it("reads a file with Windows line ends", () => {
    const [hunk] = editHunks(edit([{ kind: "add", text: "b" }]), "a\r\nb\r\n");
    expect(hunk.lines[0].new_no).toBe(2);
  });
});
