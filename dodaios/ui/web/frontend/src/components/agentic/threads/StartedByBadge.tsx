import { JARVIS_LOGO_PATH } from "@/components/brand/dodaiosLogoPath";
import { useT } from "@/i18n";

/** The lead's agent id (``dodaios.society.roster.LEAD_AGENT_ID``): Dodaios itself. */
export const LEAD_AGENT_ID = "jarvis";

/**
 * The small Dodaios mark on the lower right of a coding agent's logo: this
 * thread was opened by Dodaios (or one of its agents), not by the person.
 * Its parent must be `relative`.
 */
export function StartedByBadge({ startedBy, testId }: { startedBy: string; testId?: string }) {
  const t = useT();
  const label = startedBy === LEAD_AGENT_ID ? t("ide_threads.started_by_lead") : t("ide_threads.started_by_agent");
  return <span role="img" aria-label={label} title={label} data-testid={testId}
    className="absolute -bottom-1 -right-1 flex h-[11px] w-[11px] items-center justify-center rounded-full bg-foreground-strong ring-1 ring-black/40">
    <svg aria-hidden viewBox="0 0 256 256" className="h-[8px] w-[8px] text-background">
      <path d={JARVIS_LOGO_PATH} fillRule="evenodd" fill="currentColor" />
    </svg>
  </span>;
}
