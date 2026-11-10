/**
 * "Look" row in the app settings: the voice orb, or a look that takes its
 * place in the app (`docs/looks.md`). Picks apply at once everywhere the orb
 * shows, through the shared looks store.
 */
import { useState } from "react";
import { VoiceOrb } from "@/components/agentic/VoiceOrb";
import { fill, useT } from "@/i18n";
import { ORB_LOOK_ID } from "@/lib/looksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useActiveLook, useLooksStore } from "@/store/looks";
import { SettingsRow } from "@/views/settings/SettingsLayout";

export function LookPickerRow() {
  const t = useT();
  useActiveLook(); // loads the list on first open
  const { active, looks, loaded, failed, pick } = useLooksStore();
  const pushToast = useEventStore((s) => s.pushToast);
  const [saving, setSaving] = useState(false);

  async function onPick(id: string) {
    if (saving || id === active) return;
    setSaving(true);
    try {
      await pick(id);
      pushToast("success", t("settings_view.look.saved"));
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const options = [
    { id: ORB_LOOK_ID, name: t("settings_view.look.orb"), byline: "", preview: null as string | null },
    ...looks.map((look) => ({
      id: look.id,
      name: look.name,
      byline: fill(t("settings_view.look.by"), { author: look.author }),
      preview: look.preview_url,
    })),
  ];

  return (
    <SettingsRow
      title={t("settings_view.look.title")}
      description={t("settings_view.look.description")}
    >
      <div
        className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2.5 pt-1"
        data-testid="look-picker"
      >
        {options.map((opt) => {
          const selected = opt.id === active;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => void onPick(opt.id)}
              disabled={saving || !loaded}
              aria-pressed={selected}
              data-testid={`look-option-${opt.id}`}
              className={cn(
                "flex flex-col items-center gap-1.5 rounded-md border p-2 transition-colors disabled:opacity-60",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected
                  ? "border-accent bg-accent-soft"
                  : "border-border hover:border-border-strong hover:bg-secondary",
              )}
            >
              <div className="flex h-16 w-full items-center justify-center overflow-hidden rounded bg-background">
                {opt.preview ? (
                  <img src={opt.preview} alt="" className="h-full w-full object-contain" />
                ) : (
                  <VoiceOrb state="idle" size={56} />
                )}
              </div>
              <span
                className={cn(
                  "max-w-full truncate text-sm font-medium",
                  selected ? "text-foreground-strong" : "text-muted-foreground",
                )}
              >
                {opt.name}
              </span>
              {opt.byline && (
                <span className="max-w-full truncate text-xs text-muted-foreground">{opt.byline}</span>
              )}
            </button>
          );
        })}
      </div>
      {failed[active] && (
        <p className="text-sm text-destructive" role="alert">
          {t("settings_view.look.failed")}
        </p>
      )}
    </SettingsRow>
  );
}
