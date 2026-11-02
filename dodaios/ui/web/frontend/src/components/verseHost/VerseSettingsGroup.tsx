/**
 * Settings → General → Unreal Verse: "Remove the Verse" (README Delivery).
 *
 * The Verse is an optional download; this group shows the installed version
 * and size and removes it again (`DELETE /api/verse/install`, which stops a
 * running Verse first). It renders only while the Unreal Verse preview flag is
 * on or a Verse is installed, so the classic Verse's settings stay as they are.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useUiLanguage } from "@/i18n";
import { SettingsCard, SettingsNote, SettingsRow, SettingsSection } from "@/views/settings/SettingsLayout";
import { VERSE_STATUS_EVENT } from "./openRequest";
import { launcherText, type LauncherKey } from "./strings";
import {
  cancelOrRemoveInstall,
  fetchInstallProgress,
  fetchVerseFlags,
  formatBytes,
  type InstallProgress,
} from "./verseHostApi";

export function VerseSettingsGroup() {
  const lang = useUiLanguage();
  const t = useCallback((key: LauncherKey, vars?: Record<string, string>) => launcherText(lang, key, vars), [lang]);
  const [preview, setPreview] = useState(false);
  const [progress, setProgress] = useState<InstallProgress | null>(null);
  const [failed, setFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Once shown, the group stays for this visit, so a removal reads "Not installed".
  const [shown, setShown] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setProgress(await fetchInstallProgress());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    fetchVerseFlags().then((f) => { if (alive) setPreview(f.unreal_preview); }, () => undefined);
    void refresh();
    const onStatus = () => void refresh();
    window.addEventListener(VERSE_STATUS_EVENT, onStatus);
    return () => {
      alive = false;
      window.removeEventListener(VERSE_STATUS_EVENT, onStatus);
    };
  }, [refresh]);

  const installed = progress?.installed_version ?? null;
  const visible = preview || !!installed || shown;
  useEffect(() => {
    if (visible && !shown) setShown(true);
  }, [visible, shown]);
  if (!visible) return null;

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      setProgress(await cancelOrRemoveInstall());
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const detail = installed
    ? `${t("settings.installed", { version: installed })}${progress?.install_bytes ? ` · ${formatBytes(progress.install_bytes)}` : ""}`
    : t("settings.not_installed");

  return (
    <SettingsSection title={t("settings.title")} description={t("settings.description")}>
      <SettingsCard>
        <SettingsRow
          id="settings-verse-remove"
          testId="verse-settings-row"
          title={t("settings.remove")}
          description={detail}
          control={
            installed && !confirming ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirming(true)}>
                {t("settings.remove")}
              </Button>
            ) : undefined
          }
        >
          {failed && <SettingsNote tone="error">{t("settings.unavailable")}</SettingsNote>}
          {confirming && installed && (
            <SettingsNote tone="warning" testId="verse-settings-confirm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>{t("settings.confirm")}</span>
                <span className="flex gap-2">
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(false)}>
                    {t("install.cancel")}
                  </Button>
                  <Button variant="destructive" size="sm" disabled={busy} onClick={() => void remove()}>
                    {busy ? t("settings.removing") : t("settings.remove")}
                  </Button>
                </span>
              </div>
            </SettingsNote>
          )}
          {error && <SettingsNote tone="error">{t("failed", { reason: error })}</SettingsNote>}
        </SettingsRow>
      </SettingsCard>
    </SettingsSection>
  );
}
