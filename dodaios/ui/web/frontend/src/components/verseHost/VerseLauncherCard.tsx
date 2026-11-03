/**
 * The Unreal Verse launcher card (WP17.13): host status, open the Verse,
 * quick-start a duel, close it. Reads `GET /api/verse/status` and re-reads on
 * every `VerseStatusChanged` the socket forwards (`VERSE_STATUS_EVENT`), with a
 * slow poll as a safety net. Shown behind the `verse.unreal_preview` flag.
 *
 * The Verse is an optional download (README Delivery): while the status is
 * `not_installed` the card shows the download size and "Download the Verse",
 * then the progress with a cancel button (`VerseInstallPanel`).
 *
 * Opening hands the foreground to `Verse.exe`: the backend (the desktop
 * process) allows it to take focus and sends `lifecycle.show`; the app window
 * comes back when Verse returns focus (`focus.return_to_app`).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useUiLanguage } from "@/i18n";
import { VERSE_STATUS_EVENT } from "./openRequest";
import { VerseInstallPanel } from "./VerseInstallPanel";
import { launcherText, type LauncherKey } from "./strings";
import {
  fetchVerseStatus,
  importBrowserSettings,
  launchVerse,
  showVerse,
  stopVerse,
  type ShowReason,
  type VerseStatus,
} from "./verseHostApi";

const POLL_MS = 5000;

let importDone = false;

export function VerseLauncherCard({ className = "" }: { className?: string }) {
  const lang = useUiLanguage();
  const t = useCallback((key: LauncherKey, vars?: Record<string, string>) => launcherText(lang, key, vars), [lang]);
  const [status, setStatus] = useState<VerseStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchVerseStatus();
      if (alive.current) setStatus(next);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onStatus = () => void refresh();
    window.addEventListener(VERSE_STATUS_EVENT, onStatus);
    if (!importDone) {
      importDone = true;
      void importBrowserSettings().catch(() => { importDone = false; });
    }
    return () => {
      alive.current = false;
      window.clearInterval(timer);
      window.removeEventListener(VERSE_STATUS_EVENT, onStatus);
    };
  }, [refresh]);

  const act = useCallback(async (run: () => Promise<VerseStatus>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await run();
      if (alive.current) setStatus(next);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);

  const open = (reason: ShowReason) => act(() => showVerse(reason));
  const s = status?.status;
  const canRun = s === "stopped" || s === "running";
  const line = !status
    ? t("starting")
    : s === "running"
      ? `${t("status.running")}${status.state ? ` · ${t(`state.${status.state}` as LauncherKey)}` : ""}`
      : t(`status.${status.status}` as LauncherKey);

  return (
    <section
      data-testid="verse-launcher-card"
      aria-label={t("title")}
      className={`w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-border bg-card/95 p-4 text-card-foreground shadow-lg backdrop-blur ${className}`}
    >
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-wide">{t("title")}</h2>
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${s === "running" ? "bg-emerald-500" : s === "crashed" ? "bg-red-500" : s === "stopped" ? "bg-amber-500" : "bg-muted-foreground/40"}`}
        />
      </header>
      <p data-testid="verse-launcher-status" className="mt-2 text-sm text-muted-foreground">{line}</p>
      {status?.status === "running" && status.vram_mb !== null && (
        <p className="mt-1 text-xs tabular-nums text-muted-foreground">
          {status.vram_mb} MB{status.fps !== null ? ` · ${Math.round(status.fps)} fps` : ""}
        </p>
      )}
      {status?.status === "crashed" && status.crash_report && (
        <p className="mt-1 truncate text-xs text-muted-foreground" title={status.crash_report}>
          {t("crash_report")}: {status.crash_report}
        </p>
      )}
      {s === "not_installed" && <VerseInstallPanel onInstalled={() => void refresh()} />}
      {error && <p role="alert" className="mt-2 text-xs text-destructive">{t("failed", { reason: error })}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {canRun && (
          <>
            <button type="button" disabled={busy} onClick={() => void open("verse_view")}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {t("open")}
            </button>
            <button type="button" disabled={busy} onClick={() => void open("quick_start_duel")}
              className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50">
              {t("quick_duel")}
            </button>
          </>
        )}
        {s === "running" && (
          <button type="button" disabled={busy} onClick={() => void act(stopVerse)}
            className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
            {t("stop")}
          </button>
        )}
        {s === "crashed" && (
          <button type="button" disabled={busy} onClick={() => void act(launchVerse)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {t("retry")}
          </button>
        )}
      </div>
    </section>
  );
}

/** For tests: forget that the one-time settings import ran. */
export function resetLauncherImportForTests(): void {
  importDone = false;
}
