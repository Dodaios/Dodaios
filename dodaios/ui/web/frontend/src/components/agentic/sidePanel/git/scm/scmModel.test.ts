import { describe, expect, it } from "vitest";
import type { GraphCommit, ScmFile, ScmStatus } from "./scmApi";
import { buildRows, groupsOf, layoutGraph, parseRefs, primaryAction, workspacePath } from "./scmModel";

const file = (path: string, letter: ScmFile["letter"] = "M", status = "modified"): ScmFile => ({ path, letter, status, original: "" });

const STATUS: ScmStatus = {
  available: true,
  reason: "",
  root: "/code/app",
  prefix: "",
  branch: "main",
  head: "abc",
  detached: false,
  unborn: false,
  upstream: "origin/main",
  ahead: 0,
  behind: 0,
  operation: "",
  remotes: ["origin"],
  stashes: 0,
  merge: [],
  staged: [],
  changes: [],
  truncated: false,
  head_message: "",
};

describe("source control rows", () => {
  it("lists the groups in order and always shows Changes", () => {
    expect(groupsOf(STATUS).map((group) => group.id)).toEqual(["changes"]);
    const busy = { ...STATUS, merge: [file("a", "!")], staged: [file("b", "A")], changes: [file("c")] };
    expect(groupsOf(busy).map((group) => group.id)).toEqual(["merge", "staged", "changes"]);
  });

  it("draws a flat list sorted by path, name or status", () => {
    const groups = groupsOf({ ...STATUS, changes: [file("src/b.ts"), file("a/z.ts", "U", "untracked"), file("src/a.ts", "D", "deleted")] });
    const paths = (sort: "path" | "name" | "status") =>
      buildRows(groups, "list", sort, new Set())
        .filter((row) => row.kind === "file")
        .map((row) => (row.kind === "file" ? row.file.path : ""));
    expect(paths("path")).toEqual(["a/z.ts", "src/a.ts", "src/b.ts"]);
    expect(paths("name")).toEqual(["src/a.ts", "src/b.ts", "a/z.ts"]);
    expect(paths("status")).toEqual(["a/z.ts", "src/b.ts", "src/a.ts"]);
  });

  it("folds single-child folders together in tree mode and hides closed ones", () => {
    const groups = groupsOf({ ...STATUS, changes: [file("src/components/a.ts"), file("src/components/b.ts"), file("README.md")] });
    const rows = buildRows(groups, "tree", "path", new Set());
    expect(rows.map((row) => (row.kind === "folder" ? `dir:${row.label}` : row.kind === "file" ? row.file.path : row.key))).toEqual([
      "group:changes",
      "dir:src/components",
      "src/components/a.ts",
      "src/components/b.ts",
      "README.md",
    ]);
    const folder = rows.find((row) => row.kind === "folder")!;
    expect(folder.kind === "folder" && folder.files).toEqual(["src/components/a.ts", "src/components/b.ts"]);
    const closed = buildRows(groups, "tree", "path", new Set([folder.key]));
    expect(closed.filter((row) => row.kind === "file")).toHaveLength(1);
    expect(buildRows(groups, "tree", "path", new Set(["group:changes"]))).toHaveLength(1);
  });

  it("maps repository paths into the workspace folder", () => {
    expect(workspacePath("app/src/x.ts", "app/")).toBe("src/x.ts");
    expect(workspacePath("other/x.ts", "app/")).toBeNull();
    expect(workspacePath("x.ts", "")).toBe("x.ts");
  });
});

describe("the commit button", () => {
  it("commits while there are changes, else publishes or syncs", () => {
    expect(primaryAction({ ...STATUS, changes: [file("a")] })).toEqual({ kind: "commit", enabled: true });
    expect(primaryAction({ ...STATUS, upstream: "" })).toEqual({ kind: "publish" });
    expect(primaryAction({ ...STATUS, ahead: 2, behind: 1 })).toEqual({ kind: "sync", ahead: 2, behind: 1 });
    expect(primaryAction(STATUS)).toEqual({ kind: "commit", enabled: false });
    expect(primaryAction({ ...STATUS, upstream: "", remotes: [] })).toEqual({ kind: "commit", enabled: false });
  });

  it("continues a rebase once its conflicts are gone, and commits a merge", () => {
    expect(primaryAction({ ...STATUS, operation: "rebase", staged: [file("a")] })).toEqual({ kind: "continue", operation: "rebase" });
    expect(primaryAction({ ...STATUS, operation: "rebase", merge: [file("a", "!")] })).toEqual({ kind: "commit", enabled: true });
    expect(primaryAction({ ...STATUS, operation: "merge" })).toEqual({ kind: "commit", enabled: true });
  });
});

describe("refs and the graph", () => {
  it("reads git's decorations as badges, the current branch first", () => {
    expect(parseRefs(["refs/remotes/origin/main", "HEAD -> refs/heads/main", "tag: refs/tags/v1.0", "refs/remotes/origin/HEAD"])).toEqual([
      { kind: "head", name: "main", current: true },
      { kind: "remote", name: "origin/main", current: false },
      { kind: "tag", name: "v1.0", current: false },
    ]);
    expect(parseRefs(["HEAD"])).toEqual([]);
  });

  const commit = (id: string, parents: string[]): GraphCommit => ({ id, parents, author: "a", email: "", date: 0, refs: [], subject: id });

  it("keeps a straight history in one lane", () => {
    const rows = layoutGraph([commit("c", ["b"]), commit("b", ["a"]), commit("a", [])]);
    expect(rows.map((row) => row.lane)).toEqual([0, 0, 0]);
    expect(rows[2].bottom).toEqual([]);
  });

  it("opens a lane for a merged branch and closes it where the branch started", () => {
    // m merges f into main; f and b both come from a.
    const rows = layoutGraph([commit("m", ["b", "f"]), commit("f", ["a"]), commit("b", ["a"]), commit("a", [])]);
    expect(rows[0]).toMatchObject({ lane: 0, branches: [1], bottom: ["b", "f"] });
    expect(rows[1]).toMatchObject({ lane: 1, bottom: ["b", "a"] });
    expect(rows[2]).toMatchObject({ lane: 0, bottom: ["a", "a"] });
    expect(rows[3]).toMatchObject({ lane: 0, joins: [1], bottom: [] });
  });

  it("gives a second branch tip its own lane", () => {
    const rows = layoutGraph([commit("x", ["a"]), commit("y", ["a"]), commit("a", [])]);
    expect(rows.map((row) => row.lane)).toEqual([0, 1, 0]);
    expect(rows[2].joins).toEqual([1]);
  });
});
