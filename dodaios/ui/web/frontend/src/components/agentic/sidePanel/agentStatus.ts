import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";

/** The four colours an agent's dot can take — what a glance has to separate. */
export type AgentDotKind = "working" | "waiting" | "idle" | "error";

/** The finer reading behind a dot, shown as words. */
export type AgentStateKey =
  | "starting"
  | "working"
  | "needs_input"
  | "failed"
  | "error"
  | "exited"
  | "done"
  | "idle"
  | "stopped"
  | "unknown";

export function dotKindFor(pane: WorkspacePaneRow): AgentDotKind {
  if (pane.status === "error" || pane.activity === "failed") return "error";
  if (pane.activity === "asking") return "waiting";
  if (
    pane.activity === "working" ||
    pane.activity === "starting" ||
    pane.status === "pending"
  )
    return "working";
  return "idle";
}

export function stateKeyFor(pane: WorkspacePaneRow, kind: AgentDotKind = dotKindFor(pane)): AgentStateKey {
  if (pane.activity === "stopped" || pane.activity === "unknown") return pane.activity;
  if (kind === "working") return pane.activity === "starting" || pane.status === "pending" ? "starting" : "working";
  if (kind === "waiting") return "needs_input";
  if (kind === "error") return pane.activity === "failed" ? "failed" : "error";
  if (pane.status === "exited") return "exited";
  return pane.worked ? "done" : "idle";
}

/** Summary order: what needs the user first, then what is busy, then the rest. */
export const SUMMARY_ORDER: readonly AgentDotKind[] = ["waiting", "working", "error", "idle"];

/**
 * The coding agents of one workspace, in call-sign order.
 *
 * Shell panes are not agents and archived ones are hidden from every list —
 * the same filter the sidebar list used before it moved into the side panel.
 */
export function workspaceAgents(panes: WorkspacePaneRow[], workspaceId: string | null): WorkspacePaneRow[] {
  if (!workspaceId) return [];
  return panes
    .filter((pane) => pane.workspace_id === workspaceId && !pane.archived && pane.agent !== "shell")
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
}

/**
 * The coding agents of every workspace that shares `workspaceId`'s project
 * folder — the active workspace first, then the others by name. The Agents
 * board lists these while it does not know the projects yet.
 *
 * `folder` is the project folder the sidebar groups by; when the caller cannot
 * name it, the active workspace's own rows supply it.
 */
export function folderAgents(
  panes: WorkspacePaneRow[],
  workspaceId: string | null,
  folder?: string | null,
): WorkspacePaneRow[] {
  if (!workspaceId) return [];
  const home = folder || panes.find((pane) => pane.workspace_id === workspaceId)?.folder;
  if (!home) return workspaceAgents(panes, workspaceId);
  return panes
    .filter((pane) => pane.folder === home && !pane.archived && pane.agent !== "shell")
    .sort(
      (a, b) =>
        Number(b.workspace_id === workspaceId) - Number(a.workspace_id === workspaceId) ||
        a.workspace_name.localeCompare(b.workspace_name, undefined, { numeric: true }) ||
        a.name.localeCompare(b.name, undefined, { numeric: true }),
    );
}
