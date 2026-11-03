/**
 * "Download the Verse" on the launcher card (WP17.13, README Delivery). The
 * app install never carries the Verse; this panel shows the package size, then
 * the download progress with cancel, and hands back to the card once the
 * Verse is installed. Polls `GET /api/verse/install/progress` while a
 * download runs.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useUiLanguage } from "@/i18n";
import { launcherText, type LauncherKey } from "./strings";
import {
  cancelOrRemoveInstall,
  fetchInstallProgress,
  formatBytes,
  isInstalling,
  startInstall,
  type InstallProgress,
} from "./verseHostApi";

const RUNNING_POLL_MS = 500;
const IDLE_POLL_MS = 15000;

export function VerseInstallPanel({ onInstalled }: { onInstalled?: () => void }) {
  const lang = useUiLanguage();
  const t = useCallback((key: LauncherKey, vars?: Record<string, string>) => launcherText(lang, key, vars), [lang]);
  const [progress, setProgress] = useState<InstallProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const installedSeen = useRef(false);

  const apply = useCallback((next: InstallProgress) => {
    if (!alive.current) return;
    setProgress(next);
    if (next.state === "installed" && !installedSeen.current) {
      installedSeen.current = true;
      onInstalled?.();
    }
  }, [onInstalled]);

  const refresh = useCallback(async () => {
    try {
      apply(await fetchInstallProgress());
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, [apply]);

  const running = isInstalling(progress);
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), running ? RUNNING_POLL_MS : IDLE_POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refresh, running]);

  const act = async (run: () => Promise<InstallProgress>) => {
    setBusy(true);
    setError(null);
    try {
      apply(await run());
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  if (!progress) return null;
  const size = progress.download_bytes;
  const total = progress.total_bytes || size || 0;
  const pct = total > 0 ? Math.min(100, Math.round((progress.done_bytes / total) * 100)) : 0;

  if (progress.state === "unavailable") {
    return <p data-testid="verse-install-unavailable" className="mt-2 text-xs text-muted-foreground">{t("install.unavailable")}</p>;
  }

  return (
    <div data-testid="verse-install" className="mt-3 space-y-2">
      {running ? (
        <>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-label={t("install.download")}
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${pct}%` }} />
          </div>
          <p data-testid="verse-install-progress" className="text-xs tabular-nums text-muted-foreground">
            {progress.state === "downloading"
              ? t("install.downloading", { done: formatBytes(progress.done_bytes), total: formatBytes(total) })
              : t(progress.state === "verifying" ? "install.verifying" : "install.installing")}
          </p>
          <button type="button" disabled={busy} onClick={() => void act(cancelOrRemoveInstall)}
            className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50">
            {t("install.cancel")}
          </button>
        </>
      ) : (
        <>
          {size !== null && (
            <p data-testid="verse-install-size" className="text-xs tabular-nums text-muted-foreground">
              {t("install.size", { size: formatBytes(size) })}
            </p>
          )}
          {progress.state === "cancelled" && <p className="text-xs text-muted-foreground">{t("install.cancelled")}</p>}
          {progress.state === "failed" && progress.error && (
            <p role="alert" className="text-xs text-destructive">{t("install.failed", { reason: progress.error })}</p>
          )}
          <button type="button" disabled={busy} onClick={() => void act(startInstall)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {progress.state === "cancelled" ? t("install.resume") : progress.state === "failed" ? t("install.retry") : t("install.download")}
          </button>
          <p className="text-xs text-muted-foreground">{t("install.hint")}</p>
        </>
      )}
      {error && <p role="alert" className="text-xs text-destructive">{t("failed", { reason: error })}</p>}
    </div>
  );
}
