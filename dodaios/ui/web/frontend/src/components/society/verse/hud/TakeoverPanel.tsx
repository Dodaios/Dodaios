/**
 * The commander takes over a desk terminal: the coding pane's screen, large,
 * and the keyboard goes to the agent as if typed in the IDE.
 *
 * A pane the IDE has mounted gets every key as it is pressed (Enter, arrows,
 * Escape, Ctrl+C, paste), through the same window event the IDE's own key
 * menu uses, without moving focus to the hidden pane. A pane the IDE has not
 * mounted shows the server's replay and takes a whole prompt at a time.
 * Ctrl+Q or the close button leaves; Escape belongs to the agent.
 */
import { useEffect, useRef, useState } from "react";
import { PANE_INPUT_EVENT, type PaneInputDetail } from "@/components/agentic/ideHotkeys";
import { promptTerminal } from "@/lib/agenticIdeApi";
import { liveTerminal } from "@/lib/liveTerminals";
import { tileSnapshot, tileStamp } from "../effects/ScreensLayer";
import { paintTerminalTile, type TerminalTileFace } from "../effects/terminalCanvas";
import { keyToTerminalData, leavesTakeover } from "../effects/terminalKeys";
import { VerseDialog } from "./VerseDialog";

interface Props {
  tile: TerminalTileFace;
  t: (key: string) => string;
  onClose: () => void;
}

/** Type `data` into the pane, as the IDE's key menu does; the pane keeps its focus where it was. */
export function typeIntoPane(tile: Pick<TerminalTileFace, "workspaceId" | "names">, data: string): void {
  for (const pane of new Set(tile.names)) {
    const detail: PaneInputDetail = { workspaceId: tile.workspaceId, pane, data, focus: false };
    window.dispatchEvent(new CustomEvent(PANE_INPUT_EVENT, { detail }));
  }
}

export function TakeoverPanel({ tile, t, onClose }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const keys = useRef<HTMLTextAreaElement>(null);
  const live = !!liveTerminal(tile.workspaceId, tile.names);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Repaint whenever the pane's screen changes (and for the cursor blink).
  const tileRef = useRef(tile);
  tileRef.current = tile;
  useEffect(() => {
    let frame = 0;
    let painted = "";
    const paint = () => {
      frame = requestAnimationFrame(paint);
      const el = canvas.current;
      if (!el) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.round(el.clientWidth * dpr), h = Math.round(el.clientHeight * dpr);
      const blink = Math.floor(performance.now() / 530) % 2 === 0;
      const stamp = `${tileStamp(tileRef.current)}|${w}x${h}|${blink}`;
      if (stamp === painted || w === 0 || h === 0) return;
      painted = stamp;
      if (el.width !== w) el.width = w;
      if (el.height !== h) el.height = h;
      const ctx = el.getContext("2d");
      if (!ctx) return;
      const shot = tileSnapshot(tileRef.current);
      paintTerminalTile(ctx, 0, 0, w, h, shot.header, shot.snap, blink);
    };
    paint();
    return () => cancelAnimationFrame(frame);
  }, []);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (leavesTakeover(e)) { e.preventDefault(); onClose(); return; }
    // Ctrl+V / Shift+Insert paste through the paste event below.
    if ((e.ctrlKey && e.key.toLowerCase() === "v") || (e.shiftKey && e.key === "Insert")) return;
    const data = keyToTerminalData(e);
    if (data === null) return;
    e.preventDefault();
    e.stopPropagation();
    typeIntoPane(tile, data);
  };
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const text = e.clipboardData.getData("text");
    e.preventDefault();
    // Bracketed so a TUI takes a multi-line paste as one paste, not as Enter presses.
    if (text) typeIntoPane(tile, `\x1b[200~${text}\x1b[201~`);
  };

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

  return (
    <VerseDialog
      title={`${t("verse.takeover.title")} · ${tile.header.title}`}
      closeLabel={t("verse.card.close")}
      onClose={onClose}
      className="verse-takeover"
      initialFocus={live ? keys : undefined}
      escapeCloses={false}
    >
      <div className="verse-takeover-screen" onMouseDown={(e) => { if (live) { e.preventDefault(); keys.current?.focus(); } }}>
        <canvas ref={canvas} className="verse-takeover-canvas" aria-label={tile.header.title} />
        {live && (
          <textarea
            ref={keys}
            className="verse-takeover-keys"
            aria-label={t("verse.takeover.keys")}
            value=""
            onChange={() => undefined}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            spellCheck={false}
            autoComplete="off"
          />
        )}
      </div>
      {live ? (
        <p className="verse-takeover-hint">{t("verse.takeover.hint_live")}</p>
      ) : (
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
      )}
    </VerseDialog>
  );
}
