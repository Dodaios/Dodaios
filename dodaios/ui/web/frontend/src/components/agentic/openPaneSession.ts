/**
 * Leave the current view for the real session: the Agentic IDE with that pane
 * maximized. Shared by the three.js Verse's crew card and the Unreal Verse's
 * `VerseOpenRequested {target: "pane"}` handler, so both open the same thing.
 */
import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

export function openPaneSession(
  pane: Pick<WorkspacePaneRow, "workspace_id" | "name">,
  options: { open?: "changes" } = {},
): void {
  const events = useEventStore.getState();
  if (events.activeSection !== "agentic-ide") events.setActiveSection("agentic-ide");
  // The terminal opens full-size in the grid, live, the way the agent works in it.
  useIdeChatStore.getState().requestPane(pane.workspace_id, pane.name, {
    maximize: true,
    ...(options.open ? { open: options.open } : {}),
  });
  // A full-view side panel would hide the very pane it just focused.
  useIdeSidePanelStore.getState().setMaximized(false);
}
