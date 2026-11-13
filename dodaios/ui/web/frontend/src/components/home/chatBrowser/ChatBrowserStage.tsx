/**
 * The assistant's browser, beside the chat it works for.
 *
 * While the assistant runs a browser task (`society_browser`), a live tile
 * shows the real page and the assistant's arrow gliding to what it clicks:
 * in the assistant's panel beside its computers when that panel is open
 * (`slot.ts`), else in the top corner of the chat. A click on the tile turns it into the stage: the
 * chat moves to the left and the browser fills the right, framed by a moving
 * light while the assistant drives, with one control at its foot: take over,
 * then hand back. Tile and stage are one element and one live connection, so
 * switching never drops a frame or reconnects.
 *
 * Watching never launches a browser: the view attaches only to a browser
 * that is already open (`/browser/open`), and only while a task runs, the
 * person holds control, or the person asked for the stage. Input reaches the
 * page only after the person took control (`useBrowserView` claims it).
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, ArrowRight, Globe, Maximize2, Minimize2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentBrowserOpen } from "@/components/society/cardData";
import { useBrowserView, type BrowserViewState } from "@/components/society/card/useBrowserView";
import { BrowserCanvas } from "@/components/society/card/BrowserCanvas";
import { OPEN_AGENT_BROWSER_EVENT } from "./openEvent";
import { setAgentBrowserStaged, useAgentBrowserSlot } from "./slot";
import "./chatBrowser.css";

/** The lead agent: the assistant's own chat browses with its profile. */
export const ASSISTANT_BROWSER_AGENT = "jarvis";
/**
 * After a task ends (or the stage is made small) the view stays this long.
 * The assistant often calls its browser several times in a row; a short
 * linger closed and reopened the view between the calls (2026-11-13).
 */
export const LINGER_MS = 180_000;

type Layout = "tile" | "stage";
type Driver = "agent" | "person" | "idle";

function hostOf(url: string): string {
  try {
    const host = new URL(url).host;
    return host.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function driverOf(state: BrowserViewState): Driver {
  if (state.manual) return "person";
  if (state.running) return "agent";
  return "idle";
}

export function ChatWithBrowser({ children, agentId = ASSISTANT_BROWSER_AGENT }: { children: ReactNode; agentId?: string }) {
  const status = useAgentBrowserOpen(agentId);
  const open = status.data?.open === true && status.data.mode !== "unavailable";
  const taskRunning = status.data?.running === true;
  const [layout, setLayout] = useState<Layout>("tile");
  // The person opened the stage or holds control: the view stays attached.
  const [pinned, setPinned] = useState(false);
  const [linger, setLinger] = useState(false);
  // Each bump (a task ended, the stage was made small) restarts the linger.
  const [lingerFrom, setLingerFrom] = useState(0);
  // Hidden by the person: stays away until the next browser task starts.
  const [dismissed, setDismissed] = useState(false);
  const wasRunning = useRef(false);
  useEffect(() => {
    if (!wasRunning.current && taskRunning) setDismissed(false);
    if (wasRunning.current && !taskRunning) setLingerFrom(Date.now());
    wasRunning.current = taskRunning;
  }, [taskRunning]);
  useEffect(() => {
    if (!lingerFrom) return undefined;
    setLinger(true);
    const timer = window.setTimeout(() => setLinger(false), LINGER_MS);
    return () => window.clearTimeout(timer);
  }, [lingerFrom]);
  const live = open && !dismissed && (taskRunning || pinned || linger);
  const view = useBrowserView(agentId, live);
  const { state } = view;
  useEffect(() => { if (state.manual) setPinned(true); }, [state.manual]);
  // The assistant asked for a hand (CAPTCHA, sign-in, a second factor): show it large.
  const requestId = state.takeoverRequest?.id;
  useEffect(() => {
    if (!requestId) return;
    setPinned(true);
    setLayout("stage");
  }, [requestId]);
  // Only a closed browser or the person folds the stage; never a pause between calls.
  useEffect(() => { if (!live) setLayout("tile"); }, [live]);
  // "Open the browser" on a takeover card in this chat shows the stage here.
  useEffect(() => {
    const onOpen = (event: Event) => {
      if ((event as CustomEvent<{ agentId?: string }>).detail?.agentId !== agentId || !open) return;
      event.preventDefault();
      setDismissed(false);
      setPinned(true);
      setLayout("stage");
    };
    window.addEventListener(OPEN_AGENT_BROWSER_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_AGENT_BROWSER_EVENT, onOpen);
  }, [agentId, open]);
  const staged = live && layout === "stage";
  useEffect(() => {
    setAgentBrowserStaged(staged);
    return () => setAgentBrowserStaged(false);
  }, [staged]);
  return (
    <div className="relative flex min-h-0 flex-1 flex-row" data-testid="chat-with-browser">
      <div className={cn("relative flex min-h-0 flex-col",
        staged ? "w-[40%] min-w-[340px] max-w-[560px] shrink-0" : "flex-1")}>
        {children}
      </div>
      {live && (
        <BrowserSurface
          view={view}
          layout={layout}
          onLayout={(next) => {
            setLayout(next);
            if (next === "stage") setPinned(true);
            else if (!state.manual) { setPinned(false); setLingerFrom(Date.now()); }
          }}
          onHide={() => { setPinned(false); setLinger(false); setDismissed(true); setLayout("tile"); }}
        />
      )}
    </div>
  );
}

interface SurfaceProps {
  view: ReturnType<typeof useBrowserView>;
  layout: Layout;
  onLayout: (layout: Layout) => void;
  onHide: () => void;
}

function BrowserSurface({ view, layout, onLayout, onHide }: SurfaceProps) {
  const t = useT();
  // The assistant as its panel and the sidebar call it.
  const name = t("sidebar.conversation");
  const slot = useAgentBrowserSlot();
  const { canvas, state, control, approve, repaint } = view;
  const driver = driverOf(state);
  const needsYou = Boolean(state.takeoverRequest) && !state.manual;
  const host = hostOf(state.url);
  const staged = layout === "stage";
  const [address, setAddress] = useState("");
  useEffect(() => setAddress(state.url), [state.url]);
  useEffect(() => {
    if (!staged) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !state.manual) onLayout("tile");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [staged, state.manual, onLayout]);
  const dotState = needsYou ? "needs-you" : driver === "idle" ? "idle" : "live";
  const statusText = needsYou
    ? fill(t("agent_browser.needs_you"), { assistant: name })
    : !state.ready
    ? t("agent_browser.connecting")
    : driver === "person"
    ? t("agent_browser.you_drive")
    : driver === "agent"
    ? fill(t("agent_browser.driving"), { assistant: name })
    : t("agent_browser.ready");
  const takeOver = () => { onLayout("stage"); control("takeover", { enabled: true }); };
  const handBack = () => control("takeover", { enabled: false });
  const iconButton = "inline-flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  const enterUrl = () => {
    const url = /^https?:\/\//i.test(address) ? address : "https://" + address;
    control("navigate", { url });
  };

  const docked = !staged && slot !== null;
  if (docked && slot) {
    // Among the assistant's computers: one row with a small live picture,
    // like a computer it is connected to. A click opens the stage.
    const rowNote = needsYou
      ? fill(t("agent_browser.needs_you"), { assistant: name })
      : driver === "person"
      ? t("agent_browser.you_drive")
      : !state.ready
      ? t("agent_browser.connecting")
      : t(driver === "agent" ? "agent_browser.working" : "agent_browser.ready");
    return createPortal(
      <button type="button" data-testid="chat-browser" data-layout="row" data-docked="true" data-driver={driver}
        aria-label={t("agent_browser.expand")} onClick={() => onLayout("stage")}
        className="agent-browser-row flex min-h-8 w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="relative shrink-0">
          <Globe aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="agent-browser-live-dot absolute -bottom-0.5 -right-0.5 !h-2 !w-2" data-state={dotState} aria-hidden />
        </span>
        <span className="min-w-0 flex-1" data-testid="chat-browser-status">
          <span className="block truncate text-sm text-foreground">{fill(t("agent_browser.title"), { assistant: name })}</span>
          <span className="block truncate text-sm text-muted-foreground">{rowNote}{host && ` · ${host}`}</span>
        </span>
        <span className="agent-browser-frame agent-browser-thumb shrink-0" data-driver={driver}
          data-needs-you={needsYou ? "true" : undefined}>
          <span className="relative block h-[60px] w-[96px] overflow-hidden rounded-[8px] bg-muted">
            {/* Watching only: the canvas takes no input here. */}
            <BrowserCanvas canvas={canvas} state={state} control={control} live={false}
              ariaLabel={fill(t("agent_browser.screen"), { assistant: name })} repaint={repaint} />
          </span>
        </span>
      </button>,
      slot,
    );
  }
  const surface = (
    <section
      data-testid="chat-browser"
      data-layout={layout}
      data-driver={driver}
      aria-label={fill(t("agent_browser.title"), { assistant: name })}
      className={cn(
        staged
          ? "agent-browser-stage relative flex min-h-0 min-w-0 flex-1 flex-col border-l border-border bg-[radial-gradient(120%_90%_at_50%_0%,hsl(var(--secondary))_0%,hsl(var(--background))_70%)] px-6 pb-6 pt-4"
          : "agent-browser-tile absolute right-4 top-4 z-30 w-[300px] max-w-[45%]",
      )}
    >
      <header className={cn("flex items-center gap-2", staged ? "mb-4" : "mb-1.5 px-1")}>
        <span className="agent-browser-live-dot shrink-0" data-state={dotState} aria-hidden />
        <div className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground" data-testid="chat-browser-status">
          <span className="font-medium text-foreground">{statusText}</span>
          {host && <span> · {host}</span>}
        </div>
        <button type="button" className={iconButton} data-testid="chat-browser-resize"
          aria-label={t(staged ? "agent_browser.minimize" : "agent_browser.expand")}
          onClick={() => onLayout(staged ? "tile" : "stage")}>
          {staged ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        {!state.manual && (
          <button type="button" className={iconButton} data-testid="chat-browser-hide"
            aria-label={t("agent_browser.hide")} onClick={onHide}>
            <X size={14} />
          </button>
        )}
      </header>

      <div className={cn("flex min-h-0 flex-col", staged && "flex-1 items-center justify-center")}>
        <div
          className={cn("agent-browser-frame w-full", staged && "max-h-full")}
          data-driver={driver}
          data-needs-you={needsYou ? "true" : undefined}
          style={staged ? { maxWidth: "min(100%, calc((100vh - 220px) * 1.6))" } : undefined}
        >
          <div className="relative overflow-hidden rounded-[16px] bg-background">
            {staged && (
              <div className="flex items-center gap-1.5 border-b border-border bg-secondary/60 px-2.5 py-1.5">
                <button type="button" className={iconButton} disabled={!state.manual}
                  aria-label={t("agent_browser.back")} onClick={() => control("back")}><ArrowLeft size={14} /></button>
                <button type="button" className={iconButton} disabled={!state.manual}
                  aria-label={t("agent_browser.forward")} onClick={() => control("forward")}><ArrowRight size={14} /></button>
                <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-full bg-background px-3 py-1 text-[12.5px] text-muted-foreground">
                  <Globe size={12} className="shrink-0" aria-hidden />
                  <input
                    className="min-w-0 flex-1 bg-transparent text-foreground outline-none disabled:text-muted-foreground"
                    aria-label={t("agent_browser.address")}
                    disabled={!state.manual || state.fullWindow}
                    value={state.manual ? address : (host || address)}
                    onChange={(event) => setAddress(event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter") enterUrl(); }}
                  />
                </div>
              </div>
            )}
            <div className="relative aspect-[16/10] w-full bg-muted">
              <BrowserCanvas
                canvas={canvas}
                state={state}
                control={control}
                live
                ariaLabel={fill(t("agent_browser.screen"), { assistant: name })}
                cursorLabel={staged ? name : undefined}
                repaint={repaint}
              />
              {!staged && (
                // The tile is for watching: a click opens the stage, it never takes control.
                <button type="button" data-testid="chat-browser-open-stage"
                  className="absolute inset-0 cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  aria-label={t("agent_browser.expand")} onClick={() => onLayout("stage")} />
              )}
              {!state.ready && (
                <div className="absolute inset-0 grid place-items-center bg-muted text-[12.5px] text-muted-foreground">
                  {state.error || t("agent_browser.connecting")}
                </div>
              )}
            </div>
          </div>
        </div>

        {staged && (
          <div className="mt-5 flex flex-col items-center gap-2">
            <div className="flex items-center gap-3 rounded-full border border-border bg-background py-1.5 pl-4 pr-1.5 shadow-sm" data-testid="chat-browser-control">
              <span className="text-[13px] text-foreground">
                {state.manual ? t("agent_browser.you_drive") : needsYou ? fill(t("agent_browser.needs_you"), { assistant: name }) : fill(t("agent_browser.driving"), { assistant: name })}
              </span>
              {state.manual ? (
                <button type="button" data-testid="chat-browser-hand-back"
                  className="inline-flex h-8 items-center rounded-full bg-foreground px-4 text-[13px] font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40"
                  disabled={state.controlPending || !state.connected} onClick={handBack}>
                  {t("agent_browser.hand_back")}
                </button>
              ) : (
                <button type="button" data-testid="chat-browser-take-over"
                  className="inline-flex h-8 items-center rounded-full bg-foreground px-4 text-[13px] font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40"
                  disabled={state.controlPending || !state.connected || !state.ready} onClick={takeOver}>
                  {t("agent_browser.take_over")}
                </button>
              )}
              {state.running && !state.manual && (
                <button type="button" data-testid="chat-browser-stop"
                  className="inline-flex h-8 items-center rounded-full bg-secondary px-3 text-[13px] font-medium text-foreground transition-colors hover:bg-border"
                  onClick={() => control("cancel")}>
                  {t("agent_browser.stop")}
                </button>
              )}
            </div>
            {needsYou && state.takeoverRequest?.reason && (
              <p role="alert" className="max-w-[520px] text-center text-[12.5px] text-foreground">{state.takeoverRequest.reason}</p>
            )}
            {state.manual && (
              <p role="status" className="text-center text-[12px] text-muted-foreground">
                {fill(t("agent_browser.private_hint"), { assistant: name })}
              </p>
            )}
            {state.approval && (
              <div role="alert" className="flex items-center gap-2 text-[12.5px]">
                <span>{t("agent_browser.approval")} {state.approval.action}</span>
                <button type="button" className="rounded-full bg-foreground px-3 py-1 text-background" onClick={() => void approve(true)}>{t("agent_browser.allow")}</button>
                <button type="button" className="rounded-full bg-secondary px-3 py-1" onClick={() => void approve(false)}>{t("agent_browser.deny")}</button>
              </div>
            )}
            {state.dialog && (
              <div role="alert" className="flex items-center gap-2 text-[12.5px]">
                <span className="max-w-[360px] truncate">{state.dialog.message}</span>
                <button type="button" className="rounded-full bg-foreground px-3 py-1 text-background" onClick={() => control("dialog", { accept: true })}>{t("agent_browser.allow")}</button>
                <button type="button" className="rounded-full bg-secondary px-3 py-1" onClick={() => control("dialog", { accept: false })}>{t("agent_browser.deny")}</button>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
  return surface;
}
