import { fill } from "@/i18n";
import type { NoticeItem } from "./reduce";

/** The thread moved on to another model after its model hit a limit (`model_fallback.py`). */
export const MODEL_FALLBACK_KIND = "model_fallback";
/** Every model of the thread's fallback chain is limited; the turn stopped. */
export const MODEL_FALLBACK_EXHAUSTED_KIND = "model_fallback_exhausted";

export function isModelFallback(item: NoticeItem): boolean {
  return item.kind === MODEL_FALLBACK_KIND || item.kind === MODEL_FALLBACK_EXHAUSTED_KIND;
}

/** "17 Nov, 00:00" in the reader's language; "" for no time. */
export function limitResetLabel(at: unknown, locale: string): string {
  const seconds = typeof at === "number" ? at : Number(at);
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  return new Intl.DateTimeFormat(locale, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(seconds * 1000);
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");

/**
 * The line a model-fallback notice reads, from its fields: "Fable limit
 * reached until 17 Nov, 00:00 – continued on Opus 5.5". The backend's own
 * English sentence is the fallback for a notice without them.
 */
export function modelFallbackText(item: NoticeItem, t: (key: string) => string, locale: string): string {
  const base = "thread_turn.model_fallback";
  const data = item.data ?? {};
  if (item.kind === MODEL_FALLBACK_EXHAUSTED_KIND) {
    const rows = Array.isArray(data.models) ? (data.models as Record<string, unknown>[]) : [];
    if (!rows.length) return item.text;
    const models = rows
      .map((row) => {
        const when = limitResetLabel(row.resets_at, locale);
        const label = str(row.label) || str(row.model);
        return when ? fill(t(`${base}.model_until`), { model: label, when }) : label;
      })
      .join("; ");
    const when = limitResetLabel(data.resets_at, locale);
    return when
      ? fill(t(`${base}.exhausted_until`), { models, when })
      : fill(t(`${base}.exhausted`), { models });
  }
  const limit = str(data.limit_label) || str(data.from_label);
  const model = str(data.to_label) || str(data.to_model);
  if (!limit || !model) return item.text;
  if (data.limit === "rate") return fill(t(`${base}.rate`), { limit, model });
  const when = limitResetLabel(data.resets_at, locale);
  return when
    ? fill(t(`${base}.switched_until`), { limit, model, when })
    : fill(t(`${base}.switched`), { limit, model });
}
