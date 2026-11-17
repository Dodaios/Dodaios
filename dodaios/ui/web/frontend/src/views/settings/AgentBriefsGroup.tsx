import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAgentBriefs } from "@/hooks/useAgentBriefs";
import { fill, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { SettingsCard, SettingsNote, SettingsSection } from "@/views/settings/SettingsLayout";

/**
 * "Agent briefs" in Settings → Behavior: how the assistant briefs the person's
 * coding agents. Without wishes an agent finishes the job: it checks its own
 * work and, with tests and CI green, pushes and merges. The person writes what
 * they want otherwise, one wish per line; the assistant keeps the same list
 * when they say it in the chat. Applies to the next brief, no restart.
 *
 * Backed by /api/settings/agent-briefs (GET/PUT/DELETE) via useAgentBriefs.
 */
export function AgentBriefsGroup() {
  const t = useT();
  const { config, loading, error, saveWishes, resetWishes } = useAgentBriefs();
  const pushToast = useEventStore((s) => s.pushToast);

  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  // Coalesce a missing field to "" so a partial response never makes the
  // draft undefined (SettingsView tests share one fetch mock across groups).
  useEffect(() => {
    if (config) setDraft(config.wishes ?? "");
  }, [config]);

  const saved = config?.wishes ?? "";
  const dirty = !!config && draft !== saved;
  const isCustom = !!config?.is_custom;
  const maxChars = config?.max_chars ?? 2000;
  const tooLong = draft.trim().length > maxChars;

  async function onSave() {
    if (!dirty || tooLong) return;
    setSaving(true);
    try {
      const result = await saveWishes(draft);
      pushToast("success", t(result.is_custom ? "settings_view.agent_briefs.saved" : "settings_view.agent_briefs.reset_done"));
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function onReset() {
    setResetting(true);
    try {
      await resetWishes();
      pushToast("success", t("settings_view.agent_briefs.reset_done"));
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setResetting(false);
    }
  }

  return (
    <SettingsSection
      title={t("settings_view.agent_briefs.title")}
      description={t("settings_view.agent_briefs.description")}
      actions={
        <span
          data-testid="agent-briefs-badge"
          className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
            isCustom ? "border-accent/40 text-accent" : "border-border text-muted-foreground"
          }`}
        >
          {isCustom ? t("settings_view.agent_briefs.custom_badge") : t("settings_view.agent_briefs.default_badge")}
        </span>
      }
    >
      <SettingsCard className="flex flex-col gap-3 p-4">
        {error && <p className="text-sm text-destructive">{error}</p>}

        <SettingsNote>
          <p>
            <span className="font-medium text-foreground">{t("settings_view.agent_briefs.default_label")}</span>{" "}
            {t("settings_view.agent_briefs.default_text")}
          </p>
          <p className="mt-1.5">
            <span className="font-medium text-foreground">{t("settings_view.agent_briefs.limits_label")}</span>{" "}
            {t("settings_view.agent_briefs.limits_text")}
          </p>
        </SettingsNote>

        <div>
          <label htmlFor="agent-briefs-editor" className="mb-1.5 block text-sm font-medium text-foreground">
            {t("settings_view.agent_briefs.editor_label")}
          </label>
          <textarea
            id="agent-briefs-editor"
            data-testid="agent-briefs-editor"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={loading}
            rows={5}
            placeholder={t("settings_view.agent_briefs.placeholder")}
            className="block w-full resize-y rounded-md border border-border bg-background px-3 py-2.5 text-sm leading-relaxed text-foreground placeholder:text-foreground-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 text-xs text-muted-foreground">
            <span className={`font-mono tabular-nums ${tooLong ? "text-destructive" : ""}`}>
              {fill(t("settings_view.agent_briefs.chars"), { count: draft.trim().length, max: maxChars })}
            </span>
            <span aria-hidden> · </span>
            <span>{t("settings_view.agent_briefs.chat_hint")}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={onReset} disabled={resetting || loading || !isCustom}>
              <RotateCcw aria-hidden />
              {t("settings_view.agent_briefs.reset")}
            </Button>
            <Button size="sm" onClick={onSave} disabled={saving || loading || !dirty || tooLong}>
              {saving ? t("settings_view.saving") : t("settings_view.agent_briefs.save")}
            </Button>
          </div>
        </div>
      </SettingsCard>
    </SettingsSection>
  );
}
