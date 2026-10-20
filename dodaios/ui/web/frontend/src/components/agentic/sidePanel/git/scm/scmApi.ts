/**
 * Client for `/api/agentic-ide/git/scm`: the Git tab's source control.
 *
 * Mirrors `dodaios/agentic_ide/scm.py`. Every call names the open workspace;
 * paths are repository-relative. A failed call rejects with a
 * {@link GitApiError} whose `code` says which follow-up the UI can offer.
 */
import { GitApiError } from "@/lib/gitApi";
import { fill, translate } from "@/i18n";

/** The letter beside a file: M A D R C T U, or `!` for a conflict. */
export type ScmLetter = "M" | "A" | "D" | "R" | "C" | "T" | "U" | "I" | "!";

export interface ScmFile {
  path: string;
  letter: ScmLetter;
  /** `index_modified`, `modified`, `untracked`, `both_modified`, … */
  status: string;
  /** Where a rename or copy came from. */
  original: string;
}

export interface ScmStatus {
  available: boolean;
  reason: string;
  root: string;
  /** The workspace folder's path inside the repository ("" or `sub/`). */
  prefix: string;
  branch: string;
  head: string;
  detached: boolean;
  unborn: boolean;
  upstream: string;
  ahead: number;
  behind: number;
  operation: "" | "merge" | "rebase" | "cherry-pick" | "revert" | "bisect";
  remotes: string[];
  stashes: number;
  merge: ScmFile[];
  staged: ScmFile[];
  changes: ScmFile[];
  truncated: boolean;
  head_message: string;
}

export interface ScmRef {
  kind: "head" | "remote" | "tag";
  name: string;
  commit: string;
  date: number;
  subject: string;
  upstream: string;
}

export interface GraphCommit {
  id: string;
  parents: string[];
  author: string;
  email: string;
  date: number;
  /** `git log %D` decorations: `HEAD -> refs/heads/main`, `refs/remotes/origin/main`, `tag: refs/tags/v1`. */
  refs: string[];
  subject: string;
}

export interface GraphPage {
  commits: GraphCommit[];
  more: boolean;
  head: string;
  upstream: string;
  incoming: string[];
  outgoing: string[];
}

export type GraphScope = "auto" | "all" | "current";

export interface CommitFile {
  path: string;
  letter: ScmLetter;
  original: string;
}

export interface CommitDetails {
  id: string;
  parents: string[];
  author: string;
  email: string;
  date: number;
  committer: string;
  committer_date: number;
  message: string;
  files: CommitFile[];
  stat: string;
}

export interface CommitFileDiff {
  path: string;
  original_path: string;
  before: string | null;
  after: string | null;
  binary: boolean;
}

/** Does this app keep itself on the newest main (`[agentic_ide] follow_main`)? */
export interface FollowMain {
  enabled: boolean;
  eligible: boolean;
  /** Why it does not follow, or what blocked the last update. */
  reason: string;
  head: string;
  remote: string;
  last_check: number;
  last_update: number;
  last_subject: string;
  /** "update" | "install" | "build" | "" */
  busy: string;
  restart_pending: boolean;
  blocked_by: string[];
  /** When a git lock blocking the update was last written (epoch s); 0 = none. */
  lock_since?: number;
  /** That lock is old enough to belong to no running command: it can be removed. */
  lock_stale?: boolean;
}

async function put<T>(path: string, body: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

export interface Stash {
  ref: string;
  message: string;
  date: number;
}

const BASE = "/api/agentic-ide/git/scm";

async function failure(res: Response): Promise<GitApiError> {
  if (res.status === 404) {
    // Either the workspace closed, or a backend from before these routes.
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail === "Not Found") return new GitApiError(translate("shell_errors.git_after_restart"), "unavailable");
      if (typeof body.detail === "string") return new GitApiError(body.detail, "not_found");
    } catch {
      // Not JSON: treat it as the missing route.
    }
    return new GitApiError(translate("shell_errors.git_after_restart"), "unavailable");
  }
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const { message, code } = detail as { message: string; code?: string };
      return new GitApiError(message, code ?? "failed");
    }
    if (typeof detail === "string") return new GitApiError(detail, "failed");
  } catch {
    // Not JSON (a proxy error page): the status line is all there is to say.
  }
  return new GitApiError(fill(translate("shell_errors.git_request_failed"), { status: res.status }), "failed");
}

async function get<T>(path: string, params: Record<string, string | number>, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)])).toString();
  const res = await fetch(`${BASE}${path}?${query}`, { signal });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

async function post<T = { ok: true }>(path: string, body: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

export const scmApi = {
  status: (workspace_id: string, signal?: AbortSignal) => get<ScmStatus>("/status", { workspace_id }, signal),
  refs: (workspace_id: string) => get<{ current: string; refs: ScmRef[] }>("/refs", { workspace_id }),
  graph: (workspace_id: string, scope: GraphScope, skip: number, limit: number, signal?: AbortSignal) =>
    get<GraphPage>("/graph", { workspace_id, scope, skip, limit }, signal),
  commit: (workspace_id: string, commit: string) => get<CommitDetails>("/commit", { workspace_id, commit }),
  commitFile: (workspace_id: string, commit: string, path: string, original = "") =>
    get<CommitFileDiff>("/commit/file", { workspace_id, commit, path, original }),
  sessionFile: (workspace_id: string, pane: string, path: string, base: string) =>
    get<{ path: string; before: string | null; after: string | null; binary: boolean }>("/session-file", { workspace_id, pane, path, base }),
  followMain: () => get<FollowMain>("/follow-main", {}),
  setFollowMain: (enabled: boolean) => put<FollowMain>("/follow-main", { enabled }),
  clearFollowLock: () => post<FollowMain>("/follow-main/clear-lock", {}),
  stashes: (workspace_id: string) => get<{ stashes: Stash[] }>("/stashes", { workspace_id }),

  stage: (workspace_id: string, paths: string[]) => post("/stage", { workspace_id, paths }),
  stageAll: (workspace_id: string, tracked_only = false) => post("/stage-all", { workspace_id, tracked_only }),
  unstage: (workspace_id: string, paths: string[]) => post("/unstage", { workspace_id, paths }),
  unstageAll: (workspace_id: string) => post("/unstage-all", { workspace_id }),
  discard: (workspace_id: string, paths: string[]) => post("/discard", { workspace_id, paths }),
  discardAll: (workspace_id: string, untracked: boolean) => post("/discard-all", { workspace_id, untracked }),
  ignore: (workspace_id: string, paths: string[]) => post("/ignore", { workspace_id, paths }),
  commitChanges: (
    workspace_id: string,
    message: string,
    options: { amend?: boolean; all_changes?: boolean; include_untracked?: boolean; signoff?: boolean; no_verify?: boolean; allow_empty?: boolean } = {},
  ) => post<{ ok: true; commit: string }>("/commit", { workspace_id, message, ...options }),
  undoCommit: (workspace_id: string) => post<{ ok: true; message: string }>("/undo-commit", { workspace_id }),
  operation: (workspace_id: string, action: "continue" | "abort") => post("/operation", { workspace_id, action }),

  fetch: (workspace_id: string, options: { remote?: string; prune?: boolean; all_remotes?: boolean } = {}) =>
    post("/fetch", { workspace_id, ...options }),
  pull: (workspace_id: string, options: { rebase?: boolean; remote?: string; branch?: string } = {}) =>
    post("/pull", { workspace_id, ...options }),
  push: (workspace_id: string, options: { remote?: string; force?: boolean; tags?: boolean } = {}) =>
    post<{ ok: true; upstream: string }>("/push", { workspace_id, ...options }),
  pushTags: (workspace_id: string, remote = "") => post("/push-tags", { workspace_id, remote }),
  sync: (workspace_id: string, rebase = false) => post("/sync", { workspace_id, rebase }),
  addRemote: (workspace_id: string, name: string, url: string) => post("/remote/add", { workspace_id, name, url }),
  removeRemote: (workspace_id: string, name: string) => post("/remote/remove", { workspace_id, name }),

  checkout: (workspace_id: string, ref: string, detached = false) =>
    post<{ ok: true; branch: string }>("/checkout", { workspace_id, ref, detached }),
  createBranch: (workspace_id: string, name: string, start = "", switchTo = true) =>
    post<{ ok: true; branch: string }>("/branch/create", { workspace_id, name, start, switch: switchTo }),
  renameBranch: (workspace_id: string, name: string, old = "") => post("/branch/rename", { workspace_id, name, old }),
  deleteBranch: (workspace_id: string, name: string, force = false) => post("/branch/delete", { workspace_id, name, force }),
  merge: (workspace_id: string, ref: string) => post<{ ok: true; result: string }>("/merge", { workspace_id, ref }),
  rebase: (workspace_id: string, ref: string) => post<{ ok: true; result: string }>("/rebase", { workspace_id, ref }),
  cherryPick: (workspace_id: string, ref: string) => post<{ ok: true; result: string }>("/cherry-pick", { workspace_id, ref }),
  revert: (workspace_id: string, ref: string) => post<{ ok: true; result: string }>("/revert", { workspace_id, ref }),
  createTag: (workspace_id: string, name: string, message = "", ref = "") => post("/tag/create", { workspace_id, name, message, ref }),
  deleteTag: (workspace_id: string, name: string) => post("/tag/delete", { workspace_id, name }),

  stash: (workspace_id: string, options: { message?: string; include_untracked?: boolean; staged?: boolean } = {}) =>
    post("/stash", { workspace_id, ...options }),
  stashApply: (workspace_id: string, ref = "", pop = false) => post("/stash/apply", { workspace_id, ref, pop }),
  stashDrop: (workspace_id: string, ref = "", everything = false) => post("/stash/drop", { workspace_id, ref, everything }),
};
