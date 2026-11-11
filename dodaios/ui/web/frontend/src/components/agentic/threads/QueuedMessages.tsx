import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp, ChevronUp, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { discardQueuedMessage, editQueuedMessage, resumeAgentChatQueue, sendQueuedNow } from "@/lib/agentChatApi";
import { cn } from "@/lib/utils";

export interface QueuedEntry {
  id: string;
  text: string;
}

/**
 * The follow-ups waiting for the agent, as a tray on top of the composer.
 * A row is one line; opening it slides it up into a box that shows the whole
 * message and lets the person rewrite it before it starts. Every row can be
 * sent at once (into the running turn, or by stopping it) or taken back.
 */
export function QueuedMessages({
  sessionId,
  entries,
  paused,
  running,
  steers,
  onPausedChange,
  onProblem,
  onGiveBack,
}: {
  sessionId: string | null;
  entries: QueuedEntry[];
  paused: boolean;
  running: boolean;
  /** The agent takes a message mid-turn, so Send now never stops it. */
  steers: boolean;
  onPausedChange: (paused: boolean) => void;
  onProblem: (message: string) => void;
  /** An edit whose message started meanwhile goes back into the composer. */
  onGiveBack: (text: string) => void;
}) {
  const t = useT();
  const [openId, setOpenId] = useState<string | null>(null);
  const [edit, setEdit] = useState("");
  /** The words the open message had when it was opened (or last saved). */
  const [original, setOriginal] = useState("");
  const [saving, setSaving] = useState(false);
  const boxRef = useRef<HTMLTextAreaElement | null>(null);
  const fail = (error: unknown) => onProblem(error instanceof Error ? error.message : String(error));

  const open = entries.find((entry) => entry.id === openId) ?? null;
  const dirty = openId !== null && edit !== original;

  // The open message started (or was taken back) while it was being edited:
  // changed words are never lost, they come back into the composer.
  const editRef = useRef({ openId, edit, dirty });
  editRef.current = { openId, edit, dirty };
  useEffect(() => {
    const current = editRef.current;
    if (current.openId === null || entries.some((entry) => entry.id === current.openId)) return;
    if (current.dirty && current.edit.trim()) {
      onGiveBack(current.edit);
      onProblem(t("ide_threads.queue_edit_started"));
    }
    setOpenId(null);
  }, [entries, onGiveBack, onProblem, t]);

  // Grow with the text, up to two fifths of the window.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, window.innerHeight * 0.4)}px`;
  }, [edit, openId]);

  if (entries.length === 0) return null;

  const toggle = (entry: QueuedEntry) => {
    if (openId === entry.id) { setOpenId(null); return; }
    setOpenId(entry.id);
    setEdit(entry.text);
    setOriginal(entry.text);
    requestAnimationFrame(() => {
      const box = boxRef.current;
      if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
    });
  };

  const save = async () => {
    if (!open || !sessionId || !dirty || saving) return;
    const text = edit;
    setSaving(true);
    try {
      const edited = await editQueuedMessage(sessionId, open.id, text);
      if (!edited) {
        onGiveBack(text);
        onProblem(t("ide_threads.queue_edit_started"));
      }
      setOpenId(null);
    } catch (error) {
      fail(error);
    } finally {
      setSaving(false);
    }
  };

  const sendNow = async (entry: QueuedEntry) => {
    if (!sessionId) return;
    onPausedChange(false);
    try {
      // Unsaved words go with it: what the person reads is what is sent.
      if (openId === entry.id && dirty && edit.trim()) await editQueuedMessage(sessionId, entry.id, edit);
      if (openId === entry.id) setOpenId(null);
      await sendQueuedNow(sessionId, entry.id);
    } catch (error) {
      fail(error);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpenId(null);
    } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void save();
    }
  };

  const sendTitle = t(steers && running ? "ide_threads.send_now_steer_title"
    : running ? "ide_threads.send_now_stop_title" : "ide_threads.send_now_title");

  return <div data-testid="thread-queue"
    className="relative mx-4 -mb-3 overflow-hidden rounded-t-2xl border border-b-0 border-border bg-secondary/40 pb-3 backdrop-blur-sm">
    <div className="flex items-center justify-between gap-2 px-3 pt-1.5 text-[11px] text-muted-foreground">
      <span>{paused && !running ? t("ide_threads.queue_paused") : fill(t("ide_threads.queue_count"), { count: entries.length })}</span>
      {paused && !running && <button type="button"
        onClick={() => { onPausedChange(false); if (sessionId) void resumeAgentChatQueue(sessionId).catch(() => onPausedChange(true)); }}
        className="rounded px-1.5 py-0.5 text-foreground hover:bg-secondary">{t("ide_threads.send_next")}</button>}
    </div>
    <ul className="flex max-h-[50vh] flex-col overflow-y-auto px-1.5 pb-0.5">
      {entries.map((entry) => {
        const expanded = entry.id === openId;
        return <li key={entry.id} data-testid="thread-queue-item" data-open={expanded || undefined}
          className={cn("group rounded-xl transition-colors", expanded ? "bg-card" : "hover:bg-card/70")}>
          <div className="flex min-w-0 items-center gap-1.5 py-1 pe-1 ps-1.5">
            <button type="button" data-testid="thread-queue-open" aria-expanded={expanded}
              aria-label={t(expanded ? "ide_threads.queue_close" : "ide_threads.queue_open")}
              title={t(expanded ? "ide_threads.queue_close" : "ide_threads.queue_open")}
              onClick={() => toggle(entry)}
              className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md text-start text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <ChevronUp className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150", expanded && "rotate-180")} />
              <span className={cn("min-w-0 flex-1 truncate", expanded ? "text-muted-foreground" : "text-foreground")}>
                {expanded ? t("ide_threads.queue_edit_label") : entry.text}
              </span>
            </button>
            <button type="button" data-testid="thread-queue-send-now" title={sendTitle} onClick={() => void sendNow(entry)}
              className="flex shrink-0 items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-xs text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <ArrowUp className="h-3 w-3" />{t("ide_threads.send_now")}</button>
            <button type="button" aria-label={t("ide_threads.remove_queued")} title={t("ide_threads.remove_queued")}
              onClick={() => { if (sessionId) void discardQueuedMessage(sessionId, entry.id).catch(fail); }}
              className="rounded-full p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"><X className="h-3.5 w-3.5" /></button>
          </div>
          {expanded && <div className="px-2.5 pb-2">
            <textarea ref={boxRef} value={edit} data-testid="thread-queue-edit" aria-label={t("ide_threads.queue_edit_label")}
              onChange={(event) => setEdit(event.target.value)} onKeyDown={onKeyDown} rows={2}
              className="block max-h-[40vh] min-h-[56px] w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-6 text-foreground outline-none focus:border-border-strong" />
            <div className="mt-1.5 flex justify-end gap-1.5 text-xs">
              <button type="button" onClick={() => setOpenId(null)}
                className="rounded-full px-2.5 py-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">{t("ide_threads.queue_cancel")}</button>
              <button type="button" data-testid="thread-queue-save" disabled={!dirty || !edit.trim() || saving} onClick={() => void save()}
                className="rounded-full bg-foreground px-2.5 py-0.5 text-background transition-opacity disabled:opacity-40">{t("ide_threads.queue_save")}</button>
            </div>
          </div>}
        </li>;
      })}
    </ul>
  </div>;
}
