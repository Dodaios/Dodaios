import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { AppWindow, ExternalLink, Globe, Loader2, RotateCw } from "lucide-react";
import { fill, useT } from "@/i18n";
import { hasEmbeddedDesktopBridge } from "@/lib/embeddedDesktop";
import { openExternalUrl } from "@/lib/openExternal";
import { isLocalBrowserAddress, readBrowserInput, wordFromBrokenAddress } from "./browserAddress";
import { persistBuiltin, storedBuiltin, useIdeBrowserLinkStore } from "./ideBrowserLinks";
import { NativeBrowserPanel } from "./NativeBrowserPanel";
import { useFrameCheck, useNativeBrowserStatus } from "./nativeBrowserApi";
import { LiveBrowserPage, useAssistantBrowserStatus, type LiveRequest } from "./LiveBrowserPage";

const URL_KEY = "jarvis.agenticIde.browserUrl.v1";
function storedUrl(): string {
  try {
    return localStorage.getItem(URL_KEY) ?? "";
  } catch {
    return "";
  }
}

function persistUrl(url: string): void {
  try {
    localStorage.setItem(URL_KEY, url);
  } catch {
    /* a convenience only: the page still loads for this session */
  }
}

const TOOL_BTN =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

/**
 * The side panel's Browser surface.
 *
 * On the Windows desktop app it shows the user's own browser (Chrome, Edge or
 * Brave) with their profile and sign-ins: see `NativeBrowserPanel`. Everywhere
 * else, or when the reader picks it, it is the built-in page view below.
 */
export function BrowserTab() {
  // Fixed for the page's lifetime, so the branch never swaps hooks.
  return hasEmbeddedDesktopBridge() ? <DesktopBrowserTab /> : <FrameBrowser />;
}

function DesktopBrowserTab() {
  const [builtin, setBuiltin] = useState(storedBuiltin);
  const status = useNativeBrowserStatus(true, !builtin);
  const native = status.data?.available ? status.data : null;

  const chooseBuiltin = (value: boolean) => {
    persistBuiltin(value);
    setBuiltin(value);
  };

  if (!builtin && status.isPending) {
    return <div data-testid="ide-browser-tab" className="h-full" />;
  }
  if (native && !builtin) {
    return <NativeBrowserPanel status={native} startUrl={storedUrl() || null}
      onUseBuiltin={() => chooseBuiltin(true)} />;
  }
  return <FrameBrowser onUseNative={native ? () => chooseBuiltin(false) : undefined} />;
}

/**
 * The built-in page view: an address bar over a page.
 *
 * A local address (a dev server on localhost) loads in an embedded frame:
 * dev servers allow it, and only this page's machine can reach them. A
 * public site, a search, or a link clicked elsewhere in the IDE opens in the
 * assistant's own browser, shown live here (`LiveBrowserPage`): most public
 * sites forbid being framed by another app, and the frame stayed empty.
 *
 * Only when the assistant's browser is not available is a public address
 * framed as before: checked first (the backend asks the site for its
 * headers), and one that refuses, or does not answer, gets a note and the
 * "open in your browser" button. The frame may not navigate the app itself
 * (no `allow-top-navigation`).
 */
function FrameBrowser({ onUseNative }: { onUseNative?: () => void }) {
  const t = useT();
  // An address the old bar made from a search word ("https://github/") never
  // answers: start empty and offer the word again instead.
  const [initial] = useState(() => {
    const stored = storedUrl();
    const word = wordFromBrokenAddress(stored);
    return word ? { url: "", draft: word } : { url: stored, draft: stored };
  });
  const [url, setUrl] = useState(initial.url);
  const [draft, setDraft] = useState(initial.draft);
  // The last search sent to the person's browser (only without the assistant's
  // browser): a search engine refuses to be shown inside another app.
  const [searched, setSearched] = useState<{ query: string; url: string } | null>(null);
  // Bumped by reload: a new key remounts the frame, which works cross-origin.
  const [generation, setGeneration] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  // The assistant's browser shows public sites live. A failed status read
  // falls back to the frame, as before there was a live view.
  const agentBrowser = useAssistantBrowserStatus();
  const liveKnown = agentBrowser !== null;
  const liveAvailable = agentBrowser?.available === true;
  // What the live view should open; the restored address only on a blank browser.
  const nextRequest = useRef(1);
  const [liveRequest, setLiveRequest] = useState<LiveRequest | null>(() =>
    initial.url && !isLocalBrowserAddress(initial.url) ? { id: 0, url: initial.url, onlyIfBlank: true } : null);

  const show = (next: string) => {
    setSearched(null);
    setDraft(next);
    persistUrl(next);
    setUrl(next);
    if (liveAvailable && !isLocalBrowserAddress(next)) {
      setLiveRequest({ id: nextRequest.current++, url: next });
      return;
    }
    if (next === url) setGeneration((value) => value + 1);
  };

  // A link clicked elsewhere in the IDE opens here: a local one in the frame,
  // a public one live. Without the assistant's browser a public link goes to
  // the user's browser, because most sites refuse to be framed.
  const pending = useIdeBrowserLinkStore((state) => state.pending);
  const take = useIdeBrowserLinkStore((state) => state.take);
  useEffect(() => {
    if (!pending || !liveKnown) return;
    take(pending.id);
    if (liveAvailable || isLocalBrowserAddress(pending.url)) show(pending.url);
    else void openExternalUrl(pending.url);
    // `show` is rebuilt every render; the link is what triggers this.
  }, [pending, take, liveKnown, liveAvailable]);

  const local = !!url && isLocalBrowserAddress(url);
  // Public sites, and whatever the assistant's browser shows while no address is set.
  const live = !local && liveAvailable && (!!url || agentBrowser?.open === true);
  const framed = !local && liveKnown && !liveAvailable;
  const check = useFrameCheck(url, generation, !!url && framed);
  // A failed check shows the frame, as before there was one.
  const blocked = framed && check.data?.ok ? check.data : null;
  const showFrame = !!url && (local || (framed && !check.isPending && !(blocked && !blocked.frameable)));
  const checking = !!url && !local && (!liveKnown || (framed && check.isPending));
  let host = url;
  try {
    host = new URL(url).host;
  } catch {
    /* the raw address then */
  }
  // The page the live browser shows now. It changes `url` only through the
  // person: a local page the assistant opens stays in the live view.
  const livePage = useRef("");
  const onPageUrl = useCallback((page: string) => {
    livePage.current = page;
    if (!isLocalBrowserAddress(page)) persistUrl(page);
    if (document.activeElement !== input.current) setDraft(page);
  }, []);

  const go = (event: FormEvent) => {
    event.preventDefault();
    const entry = readBrowserInput(draft);
    if (!entry) return;
    input.current?.blur();
    if (entry.kind === "search" && !liveAvailable) {
      setSearched({ query: entry.query, url: entry.url });
      void openExternalUrl(entry.url);
      return;
    }
    show(entry.url);
  };
  const reload = () => {
    if (live) setLiveRequest({ id: nextRequest.current++, url: livePage.current || url });
    else setGeneration((value) => value + 1);
  };

  return (
    <div data-testid="ide-browser-tab" className="flex h-full min-h-0 flex-col">
      <form onSubmit={go} className="flex h-10 shrink-0 items-center gap-1 border-b border-border/60 px-2">
        <button type="button" onClick={reload} disabled={!url && !live}
          aria-label={t("ide_side_panel.browser.reload")} title={t("ide_side_panel.browser.reload")}
          data-testid="ide-browser-reload" className={TOOL_BTN}>
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
        </button>
        <input
          ref={input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onFocus={(event) => event.target.select()}
          spellCheck={false}
          autoComplete="off"
          placeholder={t("ide_side_panel.browser.placeholder")}
          aria-label={t("ide_side_panel.browser.address")}
          data-testid="ide-browser-address"
          className="h-7 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        {onUseNative && (
          <button type="button" onClick={onUseNative}
            aria-label={t("ide_side_panel.browser.native.use_native")} title={t("ide_side_panel.browser.native.use_native")}
            data-testid="ide-browser-use-native" className={TOOL_BTN}>
            <AppWindow className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
        <button type="button" onClick={() => void openExternalUrl(live ? livePage.current || url : url)} disabled={!url && !live}
          aria-label={t("ide_side_panel.browser.open_external")} title={t("ide_side_panel.browser.open_external")}
          data-testid="ide-browser-external" className={TOOL_BTN}>
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </button>
      </form>
      {searched && (
        <div data-testid="ide-browser-searched"
          className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
          <span className="min-w-0 flex-1">{fill(t("ide_side_panel.browser.searched"), { query: searched.query })}</span>
          <button type="button" onClick={() => void openExternalUrl(searched.url)} data-testid="ide-browser-search-again"
            className="shrink-0 rounded-md border border-border px-2 py-1 text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("ide_side_panel.browser.search_again")}
          </button>
        </div>
      )}
      {live ? (
        <LiveBrowserPage request={liveRequest} onPageUrl={onPageUrl} />
      ) : showFrame ? (
        // White in both themes on purpose: it is the page's own canvas, as in
        // any browser. A page without a background would otherwise draw its
        // default black text straight onto the dark theme.
        <iframe
          key={`${url}#${generation}`}
          src={url}
          title={t("ide_side_panel.tabs.browser")}
          data-testid="ide-browser-frame"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads"
          referrerPolicy="no-referrer"
          className="min-h-0 w-full flex-1 border-0 bg-white"
        />
      ) : checking ? (
        <div className="flex min-h-0 flex-1 items-center justify-center" data-testid="ide-browser-checking">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
        </div>
      ) : url && blocked ? (
        <div data-testid="ide-browser-blocked" data-reason={blocked.reason}
          className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <Globe className="h-5 w-5 text-muted-foreground" aria-hidden />
          <p className="text-sm text-foreground">
            {fill(t(blocked.reason === "refused"
              ? "ide_side_panel.browser.refused_title"
              : "ide_side_panel.browser.unreachable_title"), { host })}
          </p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {t(blocked.reason === "refused"
              ? "ide_side_panel.browser.refused_hint"
              : "ide_side_panel.browser.unreachable_hint")}
          </p>
          {blocked.reason === "refused" ? (
            <button type="button" onClick={() => void openExternalUrl(url)} data-testid="ide-browser-blocked-open"
              className="mt-1 rounded-md border border-border px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t("ide_side_panel.browser.open_external")}
            </button>
          ) : (
            <button type="button" onClick={() => setGeneration((value) => value + 1)}
              className="mt-1 rounded-md border border-border px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t("ide_side_panel.browser.reload")}
            </button>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <Globe className="h-5 w-5 text-muted-foreground" aria-hidden />
          <p className="text-sm text-foreground">{t("ide_side_panel.browser.empty_title")}</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {fill(t(liveAvailable ? "ide_side_panel.browser.empty_hint_live" : "ide_side_panel.browser.empty_hint"),
              { assistant: t("sidebar.conversation") })}
          </p>
        </div>
      )}
    </div>
  );
}
