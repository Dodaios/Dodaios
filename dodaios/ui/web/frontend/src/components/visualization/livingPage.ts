/**
 * Living pages — artifacts the assistant keeps current through a routine
 * (backend: `dodaios/artifacts/living.py`, API `/api/living-pages`).
 *
 * Tiny on purpose: the Artifacts stage imports only `isLivingSlug` eagerly;
 * the bar that reads and stops the refresh is lazy-loaded.
 */

/** The run-directory infix of a living page (`SLUG_INFIX` in living.py). */
export const LIVING_SLUG_INFIX = "__living-page__";

export function isLivingSlug(slug: string | null | undefined): boolean {
  return !!slug && slug.includes(LIVING_SLUG_INFIX);
}

export interface LivingPageState {
  id: string;
  title: string;
  slug: string;
  page_path: string;
  visual_id: string;
  updated_at: number;
  every_minutes: number;
  refreshing: boolean;
  note: string;
}

/** "10 minutes ago" in `locale`, from a unix time in seconds. */
export function relativeTime(updatedAtS: number, nowMs: number, locale: string): string {
  const seconds = Math.round(updatedAtS - nowMs / 1000);
  const abs = Math.abs(seconds);
  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    abs < 60
      ? [seconds, "second"]
      : abs < 3600
        ? [Math.round(seconds / 60), "minute"]
        : abs < 86_400
          ? [Math.round(seconds / 3600), "hour"]
          : [Math.round(seconds / 86_400), "day"];
  try {
    return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(value, unit);
  } catch {
    return new Date(updatedAtS * 1000).toLocaleString();
  }
}

/** "3 hours" in `locale`, from a cadence in minutes (whole units only). */
export function cadence(minutes: number, locale: string): string {
  const [value, unit] =
    minutes % 1440 === 0
      ? [minutes / 1440, "day"]
      : minutes % 60 === 0
        ? [minutes / 60, "hour"]
        : [minutes, "minute"];
  try {
    return new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "long" }).format(value);
  } catch {
    return `${value} ${unit}`;
  }
}
