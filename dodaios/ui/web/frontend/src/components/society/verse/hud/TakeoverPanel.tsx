/**
 * The commander takes over a desk terminal: the IDE's own xterm, at 1:1,
 * in a large Verse window. Clicks and keystrokes land on that terminal;
 * nothing here forwards them. A pane the IDE grid has not mounted is opened
 * here, so the window still shows that pane. Until the xterm is in place the
 * server's replay is drawn in the same face. Ctrl+Q or the close button
 * leaves; Escape belongs to the agent.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AgenticTerminal } from "@/components/agentic/AgenticTerminal";
import { paneFontSize } from "@/components/agentic/paneFont";
import { liveTerminal, liveTerminalsGeneration, presentTerminal, subscribeLiveTerminals } from "@/lib/liveTerminals";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import type { TerminalTileFace } from "../effects/terminalCanvas";
import { leavesTakeover } from "../effects/terminalKeys";
import { VerseDialog } from "./VerseDialog";

function escapeCss(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return value.replace(/["\\]/g, "\\$&");
}

/** True when this workspace's IDE grid already has the pane, so a second one must not be opened. */
function ideHostsThisPane(workspaceId: string, names: readonly string[]): boolean {
  if (typeof document === "undefined" || !workspaceId) return false;
  const view = document.querySelector(`[data-workspace-terminal-view="${escapeCss(workspaceId)}"]`);
  if (!view) return false;
  return names.some((name) => name !== "" && view.querySelector(`[data-testid="agentic-terminal-host-${escapeCss(name)}"]`) !== null);
}

interface Props {
  tile: TerminalTileFace;
  t: (key: string) => string;
  onClose: () => void;
}

export function TakeoverPanel({ tile, t, onClose }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const generation = useSyncExternalStore(subscribeLiveTerminals, liveTerminalsGeneration, liveTerminalsGeneration);
  const workspaceId = tile.workspaceId;
  // Name lists are rebuilt by the stage; the joined key is the stable dependency.
  const nameKey = tile.names.join("\n");
  const namesRef = useRef(tile.names);
  namesRef.current = tile.names;
  const [live, setLive] = useState(false);
  // Kept for the life of the window: closing it disposes the xterm it opened.
  const [spare, setSpare] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const names = namesRef.current;
    const release = presentTerminal(workspaceId, names, host);
    if (!release) {
      setLive(false);
      if (!ideHostsThisPane(workspaceId, names)) setSpare(true);
      return;
    }
    setLive(true);
    // After the dialog's own focus pass, so the caret lands in the terminal.
    const focus = () => liveTerminal(workspaceId, names)?.term.focus();
    focus();
    const frame = requestAnimationFrame(focus);
    const timer = window.setTimeout(focus, 50);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      release();
    };
  }, [workspaceId, nameKey, generation]);

  // Capture phase, so the terminal below does not also receive Ctrl+Q.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!leavesTakeover(event)) return;
      event.stopPropagation();
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const openChanges = () => {
    onClose();
    const events = useEventStore.getState();
    if (events.activeSection !== "agentic-ide") events.setActiveSection("agentic-ide");
    useIdeChatStore.getState().requestPane(tile.workspaceId, tile.names[0], { open: "changes" });
    // A full-screen side panel would hide the pane this just opened.
    useIdeSidePanelStore.getState().setMaximized(false);
  };

  return (
    <VerseDialog
      title={`${t("verse.takeover.title")} · ${tile.header.title}`}
      closeLabel={t("verse.card.close")}
      onClose={onClose}
      className="verse-takeover"
      escapeCloses={false}
    >
      <div className="verse-takeover-screen">
        {live !== true && tile.fallback && tile.fallback.lines.length > 0 && (
          <pre className="verse-takeover-replay">{tile.fallback.lines.join("\n")}</pre>
        )}
        <div ref={hostRef} className="verse-takeover-host" />
        {spare && (
          <div className="verse-takeover-mount" aria-hidden="true">
            <AgenticTerminal
              name={tile.names.find((name) => name !== "") ?? tile.names[0]}
              workspaceId={workspaceId}
              displayName={tile.header.title}
              appearance="dark"
              fontSize={paneFontSize()}
              active
              headerMode="none"
              sizeLead
            />
          </div>
        )}
      </div>
      <div className="verse-takeover-foot">
        <p className="verse-takeover-hint">{t("verse.takeover.hint_live")}</p>
        <button type="button" className="verse-btn" onClick={openChanges}>{t("verse.takeover.changes")}</button>
      </div>
    </VerseDialog>
  );
}
