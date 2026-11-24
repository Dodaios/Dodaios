/**
 * The words for a note's track in the person's own requests: where it was
 * shown and how those requests went, beside the others of the same period.
 * Observation only; a share appears only from the backend's minimum on (it
 * sends null below it), so a share is never worded on a handful of requests.
 */
import { fill } from "@/i18n";
import type { NoteTrack } from "@/lib/selfImprovementApi";
import { fmtPercent } from "./words";

type T = (key: string) => string;

function day(ms: number, locale: string): string {
  return new Date(ms).toLocaleDateString(locale, { day: "numeric", month: "short" });
}

/** One sentence: "Shown in 23 of your requests since Nov 24: 21 went through (91%); without it 84% of 140." */
export function trackSentence(t: T, track: NoteTrack, locale: string): string {
  const date = day(track.since_ms, locale);
  const n = track.shown.toLocaleString(locale);
  if (track.shown === 0) return fill(t("self_improvement.track.none"), { date });
  if (track.shown_share === null || track.shown_through === null) {
    return fill(t("self_improvement.track.few"), { n, date, min: track.min_requests });
  }
  const shown = {
    n,
    date,
    through: track.shown_through.toLocaleString(locale),
    pct: fmtPercent(track.shown_share, locale),
    m: track.other.toLocaleString(locale),
  };
  if (track.other_share === null) return fill(t("self_improvement.track.shown_alone"), shown);
  return fill(t("self_improvement.track.shown"), { ...shown, other_pct: fmtPercent(track.other_share, locale) });
}

/** The short phrase in the row; "" while the note was not shown in any request. */
export function trackPhrase(t: T, track: NoteTrack | null | undefined, locale: string): string {
  if (!track || track.shown === 0) return "";
  return fill(t("self_improvement.track.row"), { n: track.shown.toLocaleString(locale) });
}
