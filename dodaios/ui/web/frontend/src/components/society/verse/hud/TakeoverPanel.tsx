/**
 * The commander takes over a desk terminal: the IDE's own xterm, at 1:1,
 * inside a small Verse window. Clicks and keystrokes land on that terminal;
 * nothing here forwards them. A pane the IDE has not mounted yet keeps the
 * prompt form. Ctrl+Q or the close button leaves; Escape belongs to the agent.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { promptTerminal } from "@/lib/agenticIdeApi";
import { liveTerminal, liveTerminalsGeneration, presentTerminal, subscribeLiveTerminals } from "@/lib/liveTerminals";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import type { TerminalTileFace } from "../effects/terminalCanvas";
import { leavesTakeover } from "../effects/terminalKeys";
import { VerseDialog } from "./VerseDialog";

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
  const [live, setLive] = useState<boolean | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const names = namesRef.current;
    const release = presentTerminal(workspaceId, names, host);
    if (!release) {
      setLive(false);
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

  const send = async () => {
    const prompt = draft.trim();
    if (!prompt || sending) return;
    setSending(true);
    setError(null);
    try {
      await promptTerminal(tile.names[0], prompt, { workspaceId: tile.workspaceId, compose: false });
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

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
        <div ref={hostRef} className="verse-takeover-host" />
      </div>
      {live === true ? (
        <div className="verse-takeover-foot">
          <p className="verse-takeover-hint">{t("verse.takeover.hint_live")}</p>
          <button type="button" className="verse-btn" onClick={openChanges}>{t("verse.takeover.changes")}</button>
        </div>
      ) : live === false ? (
        <form className="verse-takeover-prompt" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <input
            className="verse-takeover-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (leavesTakeover(e)) { e.preventDefault(); onClose(); } }}
            placeholder={t("verse.takeover.placeholder")}
            aria-label={t("verse.takeover.placeholder")}
            autoFocus
          />
          <button type="submit" className="verse-btn" data-primary="true" disabled={sending || !draft.trim()}>{t("verse.takeover.send")}</button>
          {error && <p className="verse-takeover-error" role="alert">{error}</p>}
        </form>
      ) : null}
    </VerseDialog>
  );
}
