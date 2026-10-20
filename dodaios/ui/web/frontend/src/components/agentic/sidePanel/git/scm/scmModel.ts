/**
 * The pure half of the Git tab's source control: how the status letters look,
 * how the file groups turn into list or tree rows, how the commit graph's
 * lanes run, and what the commit button offers. No React, so it is tested
 * directly.
 */
import type { GraphCommit, ScmFile, ScmLetter, ScmStatus } from "./scmApi";

export type GroupId = "merge" | "staged" | "changes";
export type ViewMode = "list" | "tree";
export type SortKey = "path" | "name" | "status";

// ------------------------------------------------------------------ letters

/** The class that colours a file's name and letter (`scm-tone-*` in scm.css). */
export function letterTone(letter: ScmLetter): string {
  return `scm-tone-${letter}`;
}

/** The i18n key of a file state's tooltip word ("Modified", "Index Added", …). */
export function statusKey(status: string): string {
  return `ide_side_panel.git.scm.state.${status}`;
}

export const FILE_STATES = [
  "index_modified",
  "index_type_changed",
  "index_added",
  "index_deleted",
  "index_renamed",
  "index_copied",
  "modified",
  "type_changed",
  "deleted",
  "intent_to_add",
  "intent_to_rename",
  "untracked",
  "both_deleted",
  "added_by_us",
  "deleted_by_them",
  "added_by_them",
  "deleted_by_us",
  "both_added",
  "both_modified",
] as const;

// ------------------------------------------------------------------ paths

export const baseName = (path: string) => path.split("/").filter(Boolean).pop() ?? path;
export const dirName = (path: string) => path.split("/").slice(0, -1).join("/");

/** A repository path as a path in the workspace folder; null when it lies outside it. */
export function workspacePath(path: string, prefix: string): string | null {
  if (!prefix) return path;
  return path.startsWith(prefix) ? path.slice(prefix.length) : null;
}

/** The key that identifies one file row (the same path can sit in two groups). */
export const fileKey = (group: GroupId, path: string) => `${group}:${path}`;

// ------------------------------------------------------------------ rows

export type Row =
  | { kind: "group"; key: string; group: GroupId; count: number; open: boolean }
  | { kind: "folder"; key: string; group: GroupId; path: string; label: string; depth: number; open: boolean; files: string[] }
  | { kind: "file"; key: string; group: GroupId; file: ScmFile; depth: number };

export interface Group {
  id: GroupId;
  files: ScmFile[];
}

/** The groups the list shows, in order; an empty group is left out (Changes always shows). */
export function groupsOf(status: ScmStatus): Group[] {
  const groups: Group[] = [];
  if (status.merge.length) groups.push({ id: "merge", files: status.merge });
  if (status.staged.length) groups.push({ id: "staged", files: status.staged });
  groups.push({ id: "changes", files: status.changes });
  return groups;
}

const LETTER_ORDER: Record<string, number> = { "!": 0, U: 1, A: 2, M: 3, T: 4, R: 5, C: 6, D: 7, I: 8 };

function sortFiles(files: ScmFile[], sort: SortKey): ScmFile[] {
  const byPath = (a: ScmFile, b: ScmFile) => a.path.localeCompare(b.path);
  const copy = [...files];
  if (sort === "name") return copy.sort((a, b) => baseName(a.path).localeCompare(baseName(b.path)) || byPath(a, b));
  if (sort === "status") return copy.sort((a, b) => (LETTER_ORDER[a.letter] ?? 9) - (LETTER_ORDER[b.letter] ?? 9) || byPath(a, b));
  return copy.sort(byPath);
}

interface TreeNode {
  name: string;
  path: string;
  folders: Map<string, TreeNode>;
  files: ScmFile[];
}

function buildTree(files: ScmFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", folders: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      let next = node.folders.get(part);
      if (!next) {
        next = { name: part, path: node.path ? `${node.path}/${part}` : part, folders: new Map(), files: [] };
        node.folders.set(part, next);
      }
      node = next;
    }
    node.files.push(file);
  }
  return root;
}

function filesUnder(node: TreeNode): string[] {
  return [...node.files.map((file) => file.path), ...[...node.folders.values()].flatMap(filesUnder)];
}

/**
 * Every row the list draws, top to bottom. `closed` holds the keys of folded
 * groups and folders. In tree mode a folder with a single sub-folder and no
 * files of its own folds into it ("src/components").
 */
export function buildRows(groups: Group[], mode: ViewMode, sort: SortKey, closed: ReadonlySet<string>): Row[] {
  const rows: Row[] = [];
  for (const group of groups) {
    const groupKey = `group:${group.id}`;
    const open = !closed.has(groupKey);
    rows.push({ kind: "group", key: groupKey, group: group.id, count: group.files.length, open });
    if (!open) continue;
    if (mode === "list") {
      for (const file of sortFiles(group.files, sort)) {
        rows.push({ kind: "file", key: fileKey(group.id, file.path), group: group.id, file, depth: 1 });
      }
      continue;
    }
    const walk = (node: TreeNode, depth: number) => {
      const folders = [...node.folders.values()].sort((a, b) => a.name.localeCompare(b.name));
      for (const start of folders) {
        let folder = start;
        let label = folder.name;
        while (folder.files.length === 0 && folder.folders.size === 1) {
          folder = [...folder.folders.values()][0];
          label = `${label}/${folder.name}`;
        }
        const key = `${group.id}:dir:${folder.path}`;
        const folderOpen = !closed.has(key);
        rows.push({ kind: "folder", key, group: group.id, path: folder.path, label, depth, open: folderOpen, files: filesUnder(folder) });
        if (folderOpen) walk(folder, depth + 1);
      }
      for (const file of sortFiles(node.files, sort === "path" ? "name" : sort)) {
        rows.push({ kind: "file", key: fileKey(group.id, file.path), group: group.id, file, depth });
      }
    };
    walk(buildTree(group.files), 1);
  }
  return rows;
}

/** The file paths a row stands for: the file itself, or everything under a folder or group. */
export function pathsOfRow(row: Row, groups: Group[]): string[] {
  if (row.kind === "file") return [row.file.path];
  if (row.kind === "folder") return row.files;
  return groups.find((group) => group.id === row.group)?.files.map((file) => file.path) ?? [];
}

// ------------------------------------------------------------------ commit button

export type PrimaryAction =
  | { kind: "commit"; enabled: boolean }
  | { kind: "continue"; operation: string }
  | { kind: "publish" }
  | { kind: "sync"; ahead: number; behind: number };

/** What the big button under the message box does right now. */
export function primaryAction(status: ScmStatus): PrimaryAction {
  const hasChanges = status.staged.length + status.changes.length + status.merge.length > 0;
  if (status.operation && status.operation !== "bisect" && status.merge.length === 0 && status.operation !== "merge") {
    return { kind: "continue", operation: status.operation };
  }
  if (hasChanges || status.operation === "merge") return { kind: "commit", enabled: true };
  if (status.branch && !status.upstream && status.remotes.length > 0 && !status.unborn) return { kind: "publish" };
  if (status.upstream && (status.ahead > 0 || status.behind > 0)) return { kind: "sync", ahead: status.ahead, behind: status.behind };
  return { kind: "commit", enabled: false };
}

// ------------------------------------------------------------------ refs

export interface RefBadge {
  kind: "head" | "remote" | "tag";
  name: string;
  /** The branch HEAD points at. */
  current: boolean;
}

/** `git log %D` decorations (with `--decorate=full`) as badges; `origin/HEAD` is left out. */
export function parseRefs(refs: string[]): RefBadge[] {
  const badges: RefBadge[] = [];
  for (const raw of refs) {
    let value = raw.trim();
    let current = false;
    if (value === "HEAD") continue;
    if (value.startsWith("HEAD -> ")) {
      value = value.slice("HEAD -> ".length);
      current = true;
    }
    if (value.startsWith("tag: ")) {
      badges.push({ kind: "tag", name: value.slice("tag: refs/tags/".length), current: false });
    } else if (value.startsWith("refs/heads/")) {
      badges.push({ kind: "head", name: value.slice("refs/heads/".length), current });
    } else if (value.startsWith("refs/remotes/")) {
      const name = value.slice("refs/remotes/".length);
      if (!name.endsWith("/HEAD")) badges.push({ kind: "remote", name, current: false });
    }
  }
  // The current branch first, then branches, remotes, tags.
  const order = { head: 1, remote: 2, tag: 3 } as const;
  return badges.sort((a, b) => Number(b.current) - Number(a.current) || order[a.kind] - order[b.kind]);
}

// ------------------------------------------------------------------ graph

export interface GraphRow {
  commit: GraphCommit;
  /** The lane this commit's dot sits in. */
  lane: number;
  /** Lanes entering the row from above: [lane, its commit] (null = empty lane). */
  top: (string | null)[];
  /** Lanes leaving the row downwards. */
  bottom: (string | null)[];
  /** Lanes the commit's second and later parents leave through. */
  branches: number[];
  /** Lanes that end in this commit (other children joining it). */
  joins: number[];
  /** Lanes this row needs to draw. */
  width: number;
}

/**
 * Lane layout for commits in topological order. Each lane holds the commit it
 * is waiting for; a commit takes the first lane waiting for it (or a free one),
 * its first parent continues in that lane, every further parent takes the lane
 * already waiting for it or a free one.
 */
export function layoutGraph(commits: GraphCommit[]): GraphRow[] {
  const lanes: (string | null)[] = [];
  const rows: GraphRow[] = [];
  for (const commit of commits) {
    let lane = lanes.indexOf(commit.id);
    const top = [...lanes];
    if (lane < 0) {
      lane = lanes.indexOf(null);
      if (lane < 0) {
        lane = lanes.length;
        lanes.push(null);
      }
    }
    const joins: number[] = [];
    lanes.forEach((value, index) => {
      if (value === commit.id && index !== lane) {
        joins.push(index);
        lanes[index] = null;
      }
    });
    lanes[lane] = commit.parents[0] ?? null;
    const branches: number[] = [];
    for (const parent of commit.parents.slice(1)) {
      let target = lanes.indexOf(parent);
      if (target < 0) {
        target = lanes.indexOf(null);
        if (target < 0) {
          target = lanes.length;
          lanes.push(null);
        }
        lanes[target] = parent;
      }
      branches.push(target);
    }
    while (lanes.length && lanes[lanes.length - 1] === null) lanes.pop();
    const bottom = [...lanes];
    rows.push({ commit, lane, top, bottom, branches, joins, width: Math.max(top.length, bottom.length, lane + 1) });
  }
  return rows;
}

/** One of five lane colours, the same lane always the same one. */
export const LANE_COLORS = 5;
/** The first lane carries the checked-out branch and takes its ref colour; the others cycle. */
export const laneColor = (lane: number) => (lane === 0 ? "var(--scm-ref-local)" : `var(--scm-lane-${(lane - 1) % LANE_COLORS})`);
