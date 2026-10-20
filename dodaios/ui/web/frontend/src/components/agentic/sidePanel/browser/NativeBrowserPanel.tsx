import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { BrandedSelect } from "@/components/ui/select";
import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";

import {
  NATIVE_BROWSER_STATUS_QUERY,
  initialChoice,
  launchNativeBrowser,
  openNativeBrowserTab,
  rememberChoice,
  type NativeBrowserChoice,
  type NativeBrowserStatus,
} from "./nativeBrowserApi";
import { useIdeBrowserLinkStore } from "./ideBrowserLinks";
import { useNativePlacement } from "./useNativePlacement";

/** The window may not be shown yet right after the tab came forward: ask again. */
const OPEN_TRIES = 8;
const OPEN_RETRY_MS = 150;

const LINK_BTN =
  "rounded-md border border-border px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-secondary " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function choiceValue(choice: NativeBrowserChoice): string {
  return `${choice.browser}\n${choice.profile}`;
}

function parseChoice(value: string): NativeBrowserChoice {
  const [browser = "", profile = ""] = value.split("\n");
  return { browser, profile };
}

/**
 * The browser panel on the Windows desktop app: the user's own browser.
 *
 * A real window of the installed Chrome (or Edge, Brave) sits on top of this
 * component's body, opened with the picked profile, so every site works and
 * every sign-in is there. The browser's own tab strip and address bar are the
 * panel's only toolbar: the window fills the whole panel. What lies underneath
 * shows only while no window is there (opening, closed, failed), and that is
 * also where the profile is picked.
 */
export function NativeBrowserPanel({
  status,
  startUrl,
  onUseBuiltin,
}: {
  status: NativeBrowserStatus;
  startUrl: string | null;
  onUseBuiltin: () => void;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const owner = `panel-${useId()}`;
  const body = useRef<HTMLDivElement>(null);
  const [choice, setChoice] = useState<NativeBrowserChoice | null>(() => initialChoice(status.browsers));
  const [launching, setLaunching] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const autoStarted = useRef(false);

  const state = launching ? "launching" : status.state;
  // Resend the rectangle whenever the backend took a new window.
  const visible = useNativePlacement(body, owner, `${state}:${status.browser}:${status.profile}`);

  const options = useMemo(() => status.browsers.flatMap((browser) => browser.profiles.map((profile) => ({
    value: choiceValue({ browser: browser.id, profile: profile.directory }),
    label: profile.name,
    hint: profile.email || undefined,
    // With more than one browser installed, say which one each profile is in.
    description: status.browsers.length > 1 ? browser.label : undefined,
  }))), [status.browsers]);

  const launch = useCallback(async (next: NativeBrowserChoice, url: string | null = startUrl) => {
    setLaunching(true);
    setFailure(null);
    const result = await launchNativeBrowser(next, url);
    // A newer pick replaced this one; its own answer decides what shows.
    if (result.reason === "superseded") return;
    setLaunching(false);
    if (!result.ok) setFailure(result.reason || "launch_failed");
    queryClient.setQueryData(NATIVE_BROWSER_STATUS_QUERY, (old: NativeBrowserStatus | undefined) =>
      old ? { ...old, ...result, browsers: old.browsers } : old);
  }, [queryClient, startUrl]);

  // A link clicked elsewhere in the IDE: a new tab in the shown window, or a
  // new window on that address when there is none.
  const pending = useIdeBrowserLinkStore((store) => store.pending);
  const take = useIdeBrowserLinkStore((store) => store.take);
  const embedded = status.state === "embedded";
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => {
    if (!pending || !visible || !choice || launching) return;
    take(pending.id);
    autoStarted.current = true;
    const { url } = pending;
    if (!embedded) {
      void launch(choice, url);
      return;
    }
    void (async () => {
      for (let attempt = 0; attempt < OPEN_TRIES && mounted.current; attempt += 1) {
        const result = await openNativeBrowserTab(url);
        if (result.ok || !mounted.current) return;
        if (result.reason === "not_embedded") {
          void launch(choice, url);
          return;
        }
        if (result.reason !== "not_shown") break;
        await new Promise((resolve) => window.setTimeout(resolve, OPEN_RETRY_MS));
      }
      // The panel's window is on screen by now: the user's browser shows it there or nearby.
      if (mounted.current) void openExternalUrl(url);
    })();
  }, [pending, visible, choice, launching, embedded, take, launch]);

  // Open the window the first time the panel is on screen. A window the user
  // closed or popped out stays that way until they ask for it again.
  useEffect(() => {
    if (!visible || !choice || autoStarted.current) return;
    if (useIdeBrowserLinkStore.getState().pending) return; // the link opens the window
    autoStarted.current = true;
    const alreadyThere = status.state === "embedded"
      && status.browser === choice.browser && status.profile === choice.profile;
    if (!alreadyThere && (status.state === "idle" || status.state === "embedded" || status.state === "error")) {
      void launch(choice);
    }
  }, [visible, choice, status.state, status.browser, status.profile, launch]);

  const pick = (value: string) => {
    const next = parseChoice(value);
    setChoice(next);
    rememberChoice(next);
    void launch(next);
  };

  const browserLabel = status.browsers.find((b) => b.id === choice?.browser)?.label ?? "Chrome";

  const picker = choice && options.length > 1 && (
    <BrandedSelect
      value={choiceValue(choice)}
      options={options}
      onValueChange={pick}
      ariaLabel={t("ide_side_panel.browser.native.profile")}
      testId="ide-browser-profile"
      className="h-8 w-full max-w-xs text-sm"
    />
  );

  return (
    <div ref={body} data-testid="ide-browser-tab" data-mode="native"
      className="relative flex h-full min-h-0 flex-col items-center justify-center gap-3 px-6 text-center">
      {state === "launching" && (
        <>
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
          <p className="text-sm text-foreground">{fill(t("ide_side_panel.browser.native.opening"), { browser: browserLabel })}</p>
          <p className="max-w-xs text-xs text-muted-foreground">{t("ide_side_panel.browser.native.opening_hint")}</p>
        </>
      )}
      {state !== "launching" && (failure || state === "error") && (
        <>
          <p className="text-sm text-foreground">{t("ide_side_panel.browser.native.error_title")}</p>
          <p className="max-w-xs text-xs text-muted-foreground">
            {(failure ?? status.reason) === "browser_missing"
              ? t("ide_side_panel.browser.native.error_missing")
              : t("ide_side_panel.browser.native.error_generic")}
          </p>
          {picker}
          <div className="flex gap-2">
            {choice && <button type="button" className={LINK_BTN} onClick={() => void launch(choice)}>
              {t("ide_side_panel.browser.native.retry")}</button>}
            <button type="button" className={LINK_BTN} onClick={onUseBuiltin}>
              {t("ide_side_panel.browser.native.builtin")}</button>
          </div>
        </>
      )}
      {state !== "launching" && !failure && (state === "closed" || state === "released" || (state === "idle" && autoStarted.current)) && (
        <>
          <p className="text-sm text-foreground">
            {state === "released"
              ? t("ide_side_panel.browser.native.popped_title")
              : t("ide_side_panel.browser.native.closed_title")}
          </p>
          {picker}
          {choice && <button type="button" className={LINK_BTN} data-testid="ide-browser-reopen"
            onClick={() => void launch(choice)}>{t("ide_side_panel.browser.native.reopen")}</button>}
        </>
      )}
    </div>
  );
}
