/**
 * "Built by {name}" — the mark on an agent, a skill or a routine that the
 * self-building loop created. A click opens its build in "Built for you":
 * why it exists, how it was checked, and the undo.
 *
 * Renders nothing for anything the person (or the product) made, and nothing
 * while the ledger is not running — the join is the build's recorded artefact
 * (`GET /api/self-build/provenance`, docs/self-build.md "Artefact ids").
 */
import { BuiltIcon } from "@/components/icons/sectionIcons";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useProvenanceFor } from "@/hooks/useSelfBuild";
import { openBuild } from "@/store/selfBuildFocus";

export function BuiltByBadge({
  type,
  id,
  compact = false,
  className,
}: {
  type: "agent" | "skill" | "routine" | "memory";
  id: string | null | undefined;
  compact?: boolean;
  className?: string;
}) {
  const t = useT();
  const item = useProvenanceFor(type, id);
  if (!item) return null;
  const label = t("self_build_badge.label");
  const onTrial = item.state === "trial";
  return (
    <button
      type="button"
      data-testid="built-by-badge"
      data-build-id={item.build_id}
      data-state={item.state}
      title={`${t("self_build_badge.title")}${onTrial ? ` (${t("self_build_badge.trial")})` : ""}${item.title ? ` — ${item.title}` : ""}`}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        openBuild(item.build_id);
      }}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-border text-xs text-muted-foreground transition-colors",
        "hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        compact ? "h-5 px-1.5" : "h-6 px-2",
        className,
      )}
    >
      <BuiltIcon aria-hidden className="h-3 w-3" strokeWidth={1.8} />
      {!compact && <span className="truncate">{label}</span>}
      {onTrial && !compact && <span className="text-accent">· {t("self_build_badge.trial")}</span>}
      {onTrial && compact && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />}
    </button>
  );
}
