import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AppWindow, Globe, Loader2 } from "lucide-react";

import { BrandedSelect } from "@/components/ui/select";
import { fill, useT } from "@/i18n";

import {
  NATIVE_BROWSER_STATUS_QUERY,
  initialChoice,
  launchNativeBrowser,
  releaseNativeBrowser,
  rememberChoice,
  type NativeBrowserChoice,
  type NativeBrowserStatus,
} from "./nativeBrowserApi";
import { useNativePlacement } from "./useNativePlacement";

const TOOL_BTN =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

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
 * every sign-in is there; its own tabs and address bar are the panel's. The
 * body underneath only shows while the window is opening, closed or failed.
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
  const shown = state === "embedded"
    && status.browser === choice?.browser && status.profile === choice?.profile;
  // Resend the rectangle whenever the backend took a new window.
  const visible = useNativePlacement(body, owner, `${state}:${status.browser}:${status.profile}`);

  const options = useMemo(() => status.browsers.flatMap((browser) => browser.profiles.map((profile) => ({
    value: choiceValue({ browser: browser.id, profile: profile.directory }),
    label: profile.name,
    hint: profile.email || undefined,
    // With more than one browser installed, say which one each profile is in.
    description: status.browsers.length > 1 ? browser.label : undefined,
  }))), [status.browsers]);

  const launch = useCallback(async (next: NativeBrowserChoice) => {
    setLaunching(true);
    setFailure(null);
    const result = await launchNativeBrowser(next, startUrl);
    // A newer pick replaced this one; its own answer decides what shows.
    if (result.reason === "superseded") return;
    setLaunching(false);
    if (!result.ok) setFailure(result.reason || "launch_failed");
    queryClient.setQueryData(NATIVE_BROWSER_STATUS_QUERY, (old: NativeBrowserStatus | undefined) =>
      old ? { ...old, ...result, browsers: old.browsers } : old);
  }, [queryClient, startUrl]);

  // Open the window the first time the panel is on screen. A window the user
  // closed or popped out stays that way until they ask for it again.
  useEffect(() => {
    if (!visible || !choice || autoStarted.current) return;
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

  const popOut = async () => {
    const result = await releaseNativeBrowser(false);
    queryClient.setQueryData(NATIVE_BROWSER_STATUS_QUERY, (old: NativeBrowserStatus | undefined) =>
      old ? { ...old, ...result, browsers: old.browsers } : old);
  };

  const browserLabel = status.browsers.find((b) => b.id === choice?.browser)?.label ?? "Chrome";

  return (
    <div data-testid="ide-browser-tab" data-mode="native" className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border/60 px-2">
        <Globe className="ml-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        {choice && (
          <BrandedSelect
            value={choiceValue(choice)}
            options={options}
            onValueChange={pick}
            ariaLabel={t("ide_side_panel.browser.native.profile")}
            testId="ide-browser-profile"
            className="h-7 min-w-0 max-w-[24rem] flex-1 text-sm"
          />
        )}
        <div className="flex-1" />
        <button type="button" onClick={() => void popOut()} disabled={!shown}
          aria-label={t("ide_side_panel.browser.native.pop_out")} title={t("ide_side_panel.browser.native.pop_out")}
          data-testid="ide-browser-pop-out" className={TOOL_BTN}>
          <AppWindow className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      <div ref={body} data-testid="ide-browser-native-body"
        className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
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
            {choice && <button type="button" className={LINK_BTN} data-testid="ide-browser-reopen"
              onClick={() => void launch(choice)}>{t("ide_side_panel.browser.native.reopen")}</button>}
          </>
        )}
      </div>
    </div>
  );
}
