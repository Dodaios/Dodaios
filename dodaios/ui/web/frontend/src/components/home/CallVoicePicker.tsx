import { useEffect, useState } from "react";
import { Check, Loader2, Settings2 } from "lucide-react";

import { fetchCallVoices, setCallVoice, type CallVoices } from "@/lib/voiceApi";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/**
 * The voices the current call's engine can speak with, as a short list in
 * the call window (the gear). One list whatever speaks — a realtime provider
 * or the classic TTS — read from and written through `/api/voice/voices`,
 * which delegates to the writer each engine already has, so this picker and
 * the settings pages can never disagree. A pick applies to the running call
 * when the engine allows it; otherwise the list says it reaches the next one.
 *
 * Loaded lazily by the call window: it is not needed for first paint.
 */
export default function CallVoicePicker({ onClose }: { onClose: () => void }) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [voices, setVoices] = useState<CallVoices | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchCallVoices().then(
      (body) => { if (alive) setVoices(body); },
      () => { if (alive) setFailed(true); },
    );
    return () => { alive = false; };
  }, []);

  const pick = async (id: string) => {
    if (!voices || saving || id === voices.current) return;
    setSaving(id);
    try {
      const { applies } = await setCallVoice(id);
      setVoices({ ...voices, current: id, applies });
      pushToast("success", applies === "now" ? t("voice_call.voice_saved") : t("voice_call.voice_saved_next_call"));
    } catch (error) {
      pushToast("error", (error as Error).message || t("voice_call.voice_save_failed"));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div data-testid="call-voice-picker" className="relative flex min-h-0 flex-1 flex-col px-5 pb-2 pt-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-foreground-strong">{t("voice_call.voice_title")}</p>
        {voices?.applies === "next_call" && voices.voices.length > 0 && (
          <p className="text-xs text-muted-foreground">{t("voice_call.voice_applies_next_call")}</p>
        )}
      </div>
      <div className="mt-2 min-h-0 flex-1 overflow-y-auto" role="listbox" aria-label={t("voice_call.voice_title")}>
        {!voices && !failed && (
          <p className="flex items-center gap-2 py-2 text-sm text-muted-foreground" data-testid="call-voice-loading">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{t("voice_call.voice_loading")}
          </p>
        )}
        {failed && <p className="py-2 text-sm text-muted-foreground">{t("voice_call.voice_unavailable")}</p>}
        {voices && voices.voices.length === 0 && (
          <p className="py-2 text-sm text-muted-foreground" data-testid="call-voice-none">{t("voice_call.voice_none")}</p>
        )}
        {voices && voices.voices.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {voices.voices.map((voice) => {
              const selected = voice.id === voices.current || (!voices.current && voice.id === voices.default);
              return (
                <li key={voice.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    disabled={saving !== null}
                    onClick={() => void pick(voice.id)}
                    data-testid="call-voice-option"
                    data-voice={voice.id}
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg px-3 py-1.5 text-left text-sm transition-colors",
                      selected ? "bg-secondary text-foreground-strong" : "text-foreground hover:bg-secondary/70",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                    )}
                  >
                    <span className="truncate">{voice.label || voice.id}</span>
                    {saving === voice.id ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
                    ) : selected ? (
                      <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden />
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <footer className="flex items-center justify-between gap-3 pt-2">
        <button type="button" onClick={() => setActiveSection("voice-api-keys")} data-testid="call-voice-all-settings"
          className="inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Settings2 className="h-3.5 w-3.5" aria-hidden />{t("voice_call.all_settings")}
        </button>
        <button type="button" onClick={onClose} data-testid="call-voice-done"
          className="inline-flex h-8 items-center rounded-full bg-secondary px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {t("common.close")}
        </button>
      </footer>
    </div>
  );
}
