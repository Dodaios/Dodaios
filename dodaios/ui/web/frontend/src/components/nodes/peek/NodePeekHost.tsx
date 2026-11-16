/**
 * Where the node window is drawn: once, at the app's root.
 *
 * The window (and with it the stage and the editors) is its own chunk. It is
 * fetched while the app idles after its start, so a click on a page card
 * finds it loaded and the window is there in the same frame. A click that is
 * faster than that still gets the window at once: its frame, the node's name
 * and a close button are drawn from the entry bundle (`NodePeekFrame`), and
 * the content takes their place when it arrives. Until 2026-11-16 the first
 * click showed a dimmed page and nothing else for as long as the chunk took.
 *
 * The window belongs to the page it was opened on. A change of section (a
 * spoken "go to settings", a link in the conversation, "Open in Nodes")
 * closes it, so it never hangs over a page it has nothing to do with.
 */
import { Suspense, lazy, useEffect } from "react";
import { FileText, Loader2, X } from "lucide-react";

import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useNodePeek, type NodePeekRequest } from "@/store/nodePeek";
import { PEEK_FRAME_CLASS, PEEK_SCRIM_CLASS, loadNodePeekWindow, preloadNodePeek } from "./peekFrame";

const NodePeekWindow = lazy(loadNodePeekWindow);

/** After the app's own start is through: the first seconds belong to the page. */
const PRELOAD_AFTER_MS = 2500;

export function NodePeekHost() {
  const peek = useNodePeek((s) => s.peek);
  useEffect(
    () =>
      useEventStore.subscribe((state, previous) => {
        if (state.activeSection !== previous.activeSection) useNodePeek.getState().close();
      }),
    [],
  );
  useEffect(() => {
    // Not in tests: a suite that never opens the window must not load its chunk.
    if (import.meta.env.MODE === "test") return;
    let idle: number | undefined;
    const timer = window.setTimeout(() => {
      if (typeof window.requestIdleCallback === "function") {
        idle = window.requestIdleCallback(() => preloadNodePeek(), { timeout: 4000 });
      } else {
        preloadNodePeek();
      }
    }, PRELOAD_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      if (idle !== undefined) window.cancelIdleCallback(idle);
    };
  }, []);
  if (peek === null) return null;
  return (
    <Suspense fallback={<NodePeekFrame peek={peek} />}>
      <NodePeekWindow peek={peek} />
    </Suspense>
  );
}

/**
 * The window before its content: the same frame in the same place, the
 * node's name, and the ways out (the close button, Escape, a click beside
 * it). The content replaces it without the frame moving.
 */
function NodePeekFrame({ peek }: { peek: NodePeekRequest }) {
  const t = useT();
  const close = useNodePeek((s) => s.close);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);
  const title = peek.title || peek.path.split("/").pop() || t("nodes.peek.window");
  return (
    <div className="fixed inset-0 z-[60]" data-testid="node-peek-loading">
      <div aria-hidden onClick={close} className={PEEK_SCRIM_CLASS} />
      <div role="dialog" aria-modal="true" aria-busy="true" aria-label={title} className={PEEK_FRAME_CLASS}>
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center gap-3 border-b border-border py-2.5 pl-4 pr-3">
            <div className="flex h-10 min-w-0 flex-1 items-center gap-2.5 px-1">
              <FileText className="h-4 w-4 shrink-0 text-primary" aria-hidden />
              <span className="truncate text-base font-medium text-foreground-strong">{title}</span>
            </div>
            <button
              type="button"
              onClick={close}
              aria-label={t("visualization.close")}
              title={t("visualization.close")}
              data-testid="node-peek-loading-close"
              className={
                "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 text-muted-foreground " +
                "transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              }
            >
              <X className="h-[18px] w-[18px]" aria-hidden />
            </button>
          </div>
          <div role="status" className="flex min-h-0 flex-1 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        </section>
      </div>
    </div>
  );
}
