/**
 * A public site in the side panel's Browser tab, shown live from the
 * assistant's own browser.
 *
 * Most public sites forbid being shown inside another app (GitHub, Google,
 * most sign-ins), so the built-in frame could only say "cannot be shown
 * here". The assistant's browser is a real Chromium that the app already
 * streams live (the chat's browser stage), so the tab shows that picture and
 * forwards the person's clicks, scrolling and typing to it. It is the same
 * browser the assistant works in: while it drives, the tab shows it working
 * with its arrow.
 *
 * Input needs control of the browser, and a held control pauses the
 * assistant's browser tasks. So the tab takes control only for what the
 * person does (an address, a click, a key), and hands it back after a short
 * pause without input. A click after that takes it again on its own.
 *
 * The page is laid out for the panel: the tab tells the browser how large its
 * stage is, so the page fills it like in any browser window instead of being
 * a small picture of a wide page. That holds while the tab shows; the
 * assistant's own tasks always run at the browser's usual size.
 */
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { fill, useT } from "@/i18n";
import { BrowserCanvas, type BrowserControl } from "@/components/society/card/BrowserCanvas";
import { useBrowserView } from "@/components/society/card/useBrowserView";
import { ASSISTANT_BROWSER_AGENT } from "@/components/home/chatBrowser/ChatBrowserStage";

/** Without input for this long, control goes back to the assistant. */
export const IDLE_HANDBACK_MS = 30_000;
/** A resized panel settles for this long before the page is laid out again. */
export const VIEWPORT_SETTLE_MS = 150;
/** The page size the browser accepts (`VIEW_MIN` / `VIEW_MAX` in live_runner.py). */
const MIN_PAGE = { width: 320, height: 240 };
const MAX_PAGE = { width: 2560, height: 2560 };
/** The picture's size before the first one arrived: the browser's usual page. */
const USUAL_PAGE = { width: 1280, height: 800 };
/** Takeover attempts for one address before the tab gives up on it. */
const MAX_TAKEOVER_TRIES = 2;

export interface LiveRequest {
  id: number;
  url: string;
  /**
   * An address restored from the last session: opened only on a blank
   * browser, so reopening the tab never takes the page from the assistant.
   */
  onlyIfBlank?: boolean;
}

export interface AssistantBrowserStatus {
  /** The assistant's browser can run here (installed or installable). */
  available: boolean;
  /** It is running now. */
  open: boolean;
}

const STATUS_POLL_MS = 4_000;

/**
 * Whether the assistant's browser can show pages here, and whether it is
 * running. `null` while the first answer is out. A read that never launches
 * the browser; a failed read counts as unavailable, so the tab falls back to
 * the frame.
 */
export function useAssistantBrowserStatus(): AssistantBrowserStatus | null {
  const [status, setStatus] = useState<AssistantBrowserStatus | null>(null);
  useEffect(() => {
    let live = true;
    let timer = 0;
    const read = async () => {
      let next: AssistantBrowserStatus = { available: false, open: false };
      try {
        const response = await fetch(`/api/society/agents/${encodeURIComponent(ASSISTANT_BROWSER_AGENT)}/browser/open`);
        if (response.ok) {
          const body = (await response.json()) as { mode?: string; open?: boolean };
          next = { available: !!body && typeof body.mode === "string" && body.mode !== "unavailable", open: body?.open === true };
        }
      } catch {
        /* unavailable: the frame view stays usable */
      }
      if (!live) return;
      setStatus((old) => old && old.available === next.available && old.open === next.open ? old : next);
      timer = window.setTimeout(() => void read(), STATUS_POLL_MS);
    };
    void read();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, []);
  return status;
}

function isBlankPage(url: string): boolean {
  return !url || url === "about:blank" || url.startsWith("chrome://newtab") || url.startsWith("chrome://new-tab-page");
}

interface Props {
  /** The address to open; a new request (new id) opens it again. */
  request: LiveRequest | null;
  /** The page the browser shows now, for the address bar. */
  onPageUrl: (url: string) => void;
}

/**
 * Whether `ref` is on screen. The side panel keeps the Browser tab mounted
 * behind other tabs (`hidden`); the live picture streams only while it shows.
 */
function useOnScreen(ref: RefObject<HTMLElement>): boolean {
  const [onScreen, setOnScreen] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) setOnScreen(entry.isIntersecting);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return onScreen;
}

/**
 * The size of the stage in whole pixels once it has settled, or `null` while
 * it is not measured (hidden, or no layout yet).
 */
function useSettledSize(ref: RefObject<HTMLElement>): { width: number; height: number } | null {
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    let timer = 0;
    const read = () => {
      const box = el.getBoundingClientRect();
      const width = Math.floor(box.width);
      const height = Math.floor(box.height);
      setSize((old) => width < 1 || height < 1 ? null
        : old && old.width === width && old.height === height ? old : { width, height });
    };
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(read, VIEWPORT_SETTLE_MS);
    });
    observer.observe(el);
    read();
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [ref]);
  return size;
}

export function LiveBrowserPage({ request, onPageUrl }: Props) {
  const t = useT();
  // The assistant as the sidebar and the chat's browser stage call it.
  const name = t("sidebar.conversation");
  const root = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(root);
  const { canvas, state, control, repaint } = useBrowserView(ASSISTANT_BROWSER_AGENT, onScreen);
  const stage = useRef<HTMLDivElement>(null);
  const stageSize = useSettledSize(stage);
  const sentPage = useRef("");
  const lastInput = useRef(0);
  const tries = useRef(0);
  const [want, setWant] = useState<LiveRequest | null>(request);
  useEffect(() => {
    tries.current = 0;
    setWant(request);
  }, [request]);

  // Every input from the person counts as activity; the tab's own hand-back does not.
  const act = useCallback<BrowserControl>((op, args) => {
    if (op !== "takeover") lastInput.current = Date.now();
    control(op, args);
  }, [control]);

  // Open the wanted address: take control first, then navigate.
  useEffect(() => {
    if (!want || !state.connected || !state.ready) return;
    if (want.onlyIfBlank && (state.running || !isBlankPage(state.url))) {
      setWant(null);
      return;
    }
    if (!state.manual) {
      if (state.controlPending) return;
      if (tries.current >= MAX_TAKEOVER_TRIES) {
        setWant(null);
        return;
      }
      tries.current += 1;
      lastInput.current = Date.now();
      control("takeover", { enabled: true });
      return;
    }
    lastInput.current = Date.now();
    control("navigate", { url: want.url });
    setWant(null);
  }, [want, state.connected, state.ready, state.manual, state.controlPending, state.running, state.url, control]);

  // Lay the page out for the panel. A real Chrome window (`fullWindow`) has
  // its own size. Sent again after a reconnect: a new browser starts at its
  // usual size. Held while control changes hands, when the view drops input.
  useEffect(() => {
    if (!state.connected || !state.ready) {
      sentPage.current = "";
      return;
    }
    if (!stageSize || state.fullWindow || state.controlPending) return;
    const width = Math.min(Math.max(stageSize.width, MIN_PAGE.width), MAX_PAGE.width);
    const height = Math.min(Math.max(stageSize.height, MIN_PAGE.height), MAX_PAGE.height);
    const key = `${width}x${height}`;
    if (sentPage.current === key) return;
    sentPage.current = key;
    control("viewport", { width, height });
  }, [stageSize, state.connected, state.ready, state.fullWindow, state.controlPending, control]);

  // Hand control back after a pause, unless the assistant asked the person for a hand.
  const waitingForYou = Boolean(state.takeoverRequest);
  useEffect(() => {
    if (!state.manual || waitingForYou) return undefined;
    const timer = window.setInterval(() => {
      if (Date.now() - lastInput.current >= IDLE_HANDBACK_MS) control("takeover", { enabled: false });
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [state.manual, waitingForYou, control]);

  useEffect(() => {
    if (/^https?:\/\//i.test(state.url)) onPageUrl(state.url);
  }, [state.url, onPageUrl]);

  const frame = state.frameWidth && state.frameHeight
    ? { width: state.frameWidth, height: state.frameHeight } : USUAL_PAGE;
  const needsYou = waitingForYou && !state.manual;
  const agentDrives = state.running && !state.manual;
  const driver = state.manual ? "person" : state.running ? "agent" : "idle";
  const waiting = state.busy
    ? t("society.browser_live.busy_task").replace(/\{0\}/g, state.busy.holderName)
    : state.error || t("agent_browser.connecting");

  return (
    <div ref={root} data-testid="ide-browser-live" data-driver={driver} className="flex min-h-0 flex-1 flex-col">
      {(needsYou || agentDrives) && (
        <div data-testid="ide-browser-live-status" role="status"
          className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
          <span className="agent-browser-live-dot shrink-0" data-state={needsYou ? "needs-you" : "live"} aria-hidden />
          <span className="min-w-0 flex-1 truncate">
            {fill(t(needsYou ? "agent_browser.needs_you" : "agent_browser.driving"), { assistant: name })}
            {needsYou && state.takeoverRequest?.reason ? ` · ${state.takeoverRequest.reason}` : ""}
          </span>
        </div>
      )}
      {/* The picture keeps the page's own shape and fits the panel either way.
          A page laid out for the panel fills it; the assistant's wider page
          (while it works) is shown whole at the top. */}
      <div ref={stage} data-testid="ide-browser-live-stage"
        className="flex min-h-0 flex-1 items-start justify-center overflow-hidden bg-muted [container-type:size]">
        <div className="relative bg-muted"
          style={{ aspectRatio: `${frame.width} / ${frame.height}`, width: `min(100cqw, ${(100 * frame.width) / frame.height}cqh)` }}>
          <BrowserCanvas
            canvas={canvas}
            state={state}
            control={act}
            live
            ariaLabel={fill(t("agent_browser.screen"), { assistant: name })}
            cursorLabel={name}
            repaint={repaint}
          />
          {!state.ready && (
            <div data-testid="ide-browser-live-waiting"
              className="absolute inset-0 grid place-items-center bg-muted p-4 text-center text-xs text-muted-foreground">
              {waiting}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
