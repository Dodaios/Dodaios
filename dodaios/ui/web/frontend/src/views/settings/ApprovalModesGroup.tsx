/**
 * Settings → General → Permission modes: `[safety] approval_mode` (app-owned work:
 * voice, tasks, missions) and `[safety] agent_approval_mode` (what a NEW agent
 * starts with). One PUT to `/api/settings/approval-modes` saves and applies at
 * once. "Apply to all agents" sets the chosen agent mode on every existing
 * agent through `/api/society/approval-mode`; each agent can still change its
 * own mode on its card afterwards.
 */
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import { SettingsCard, SettingsNote, SettingsRow, SettingsSection, SettingsSegmented } from "@/views/settings/SettingsLayout";

export type AppMode = "bypass" | "ask";
export type AgentMode = "bypass" | "ask" | "always_ask";

interface Modes {
  app_mode: AppMode;
  agent_mode: AgentMode;
}

const APP_MODES: readonly AppMode[] = ["bypass", "ask"];
const AGENT_MODES: readonly AgentMode[] = ["bypass", "ask", "always_ask"];

async function readError(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  const detail = (body as { detail?: unknown }).detail;
  return typeof detail === "string" ? detail : `HTTP ${res.status}`;
}

export function ApprovalModesGroup() {
  const t = useT();
  const [modes, setModes] = useState<Modes | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    fetch("/api/settings/approval-modes")
      .then(async (res) => {
        if (!res.ok) throw new Error(await readError(res));
        return res.json() as Promise<Modes>;
      })
      .then((data) => { if (alive) setModes(data); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);

  const save = useCallback(async (patch: Partial<Modes>) => {
    setError(null);
    setNotes([]);
    setBusy(true);
    try {
      const res = await fetch("/api/settings/approval-modes", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) throw new Error(await readError(res));
      const data = (await res.json()) as Modes;
      setModes({ app_mode: data.app_mode, agent_mode: data.agent_mode });
    } catch (err) {
      setError(fill(t("settings_view.approvals.save_error"), { detail: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }, [t]);

  const applyToAll = useCallback(async () => {
    if (!modes) return;
    setError(null);
    setNotes([]);
    setBusy(true);
    try {
      const res = await fetch("/api/society/approval-mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: modes.agent_mode }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const data = (await res.json()) as { changed: string[]; skipped: unknown[] };
      const lines = [fill(t("settings_view.approvals.apply_all_done"), { count: String(data.changed.length) })];
      if (data.skipped.length) {
        lines.push(fill(t("settings_view.approvals.apply_all_skipped"), { count: String(data.skipped.length) }));
      }
      setNotes(lines);
    } catch (err) {
      setError(fill(t("settings_view.approvals.save_error"), { detail: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }, [modes, t]);

  return (
    <SettingsSection title={t("settings_view.approvals.title")} description={t("settings_view.approvals.description")}>
      {failed ? (
        <SettingsNote tone="error">{t("settings_view.approvals.unavailable")}</SettingsNote>
      ) : !modes ? (
        <SettingsCard><div className="h-24" aria-busy="true" /></SettingsCard>
      ) : (
        <SettingsCard>
          <SettingsRow
            id="settings-approvals-app"
            testId="approvals-app-mode"
            title={t("settings_view.approvals.app_title")}
            description={t("settings_view.approvals.app_description")}
            control={
              <SettingsSegmented<AppMode>
                value={modes.app_mode}
                ariaLabel={t("settings_view.approvals.app_title")}
                disabled={busy}
                options={APP_MODES.map((mode) => ({ value: mode, label: t(`settings_view.approvals.modes.${mode}`) }))}
                onChange={(mode) => void save({ app_mode: mode })}
              />
            }
          />
          <SettingsRow
            id="settings-approvals-agents"
            testId="approvals-agent-mode"
            title={t("settings_view.approvals.agent_title")}
            description={t("settings_view.approvals.agent_description")}
          >
            <div className="flex flex-wrap items-center gap-3">
              <SettingsSegmented<AgentMode>
                value={modes.agent_mode}
                ariaLabel={t("settings_view.approvals.agent_title")}
                disabled={busy}
                options={AGENT_MODES.map((mode) => ({ value: mode, label: t(`settings_view.approvals.modes.${mode}`) }))}
                onChange={(mode) => void save({ agent_mode: mode })}
              />
              <Button size="sm" variant="outline" disabled={busy} data-testid="approvals-apply-all" onClick={() => void applyToAll()}>
                {t("settings_view.approvals.apply_all")}
              </Button>
            </div>
          </SettingsRow>
        </SettingsCard>
      )}
      <SettingsNote className="mt-2">{t("settings_view.approvals.always_on")}</SettingsNote>
      {notes.map((note) => <SettingsNote key={note} className="mt-2">{note}</SettingsNote>)}
      {error && <SettingsNote tone="error" className="mt-2">{error}</SettingsNote>}
    </SettingsSection>
  );
}
