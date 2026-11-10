/**
 * What each Dodaios agent spent, and what the assistant itself spent.
 *
 * One quiet list, readable at a glance: the agent's face and name, a bar for
 * its share, the amount and the tokens. The assistant sits on top, every
 * other agent follows by cost. A row is a filter like every other row in the
 * section: clicking it narrows the whole page to that agent.
 *
 * Coding threads and the Agentic IDE belong to no agent and are not listed
 * here; the totals above still count them.
 */
import { useMemo, useState } from "react";

import { AgentSwatch, LEAD_COLOR, agentColor } from "@/components/society/AgentSwatch";
import { useSocietyRoster, type AgentPalette, type SocietyAgent } from "@/components/society/data";
import { EmptyRow, Panel, PanelHeader } from "@/components/extensions/primitives";
import { formatExact, formatTokensOrNone } from "@/components/costs/costFormat";
import type { CostAgentBucket } from "@/hooks/useCosts";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/** Rows shown before "Show all": enough for a normal team, short for a big one. */
const FIRST_ROWS = 8;
const NO_PALETTE: AgentPalette = { primary: "", secondary: "", accent: "" };

/** "QA Hermes (deleted qa-hermes)" → "QA Hermes": the suffix is roster bookkeeping. */
export function agentDisplayName(row: Pick<CostAgentBucket, "key" | "name">): string {
  const name = row.name.replace(/\s*\(deleted [^)]*\)\s*$/i, "").trim();
  return name || row.key;
}

export function AgentSpendPanel({
  rows,
  active,
  onToggle,
  money,
  loading,
}: {
  rows: CostAgentBucket[];
  active: string[];
  onToggle: (agentId: string) => void;
  money: (usd: number) => string;
  loading?: boolean;
}) {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName) ?? "";
  const roster = useSocietyRoster();
  const [showAll, setShowAll] = useState(false);

  const byId = useMemo(() => {
    const map = new Map<string, SocietyAgent>();
    for (const agent of roster.data?.agents ?? []) map.set(agent.agentId, agent);
    return map;
  }, [roster.data]);

  // The assistant first, then the agents by what they spent.
  const ordered = useMemo(() => {
    const lead = rows.filter((r) => r.lead);
    const others = rows.filter((r) => !r.lead);
    return [...lead, ...others];
  }, [rows]);

  const leadUsd = rows.filter((r) => r.lead).reduce((sum, r) => sum + r.cost_usd, 0);
  const agentsUsd = rows.filter((r) => !r.lead).reduce((sum, r) => sum + r.cost_usd, 0);
  const agentCount = rows.filter((r) => !r.lead).length;
  // The bar compares agents with each other, not with the coding CLIs in the
  // page total: next to a month of coding the agents would all read as zero.
  const maxUsd = Math.max(0, ...rows.map((r) => r.cost_usd));
  const visible = showAll ? ordered : ordered.slice(0, FIRST_ROWS);
  const leadName = assistantName.trim() || t("costs_view.agents_lead_fallback");

  return (
    <Panel>
      <div className="px-4 pt-4">
        <PanelHeader title={fill(t("costs_view.agents_title"), { name: leadName })} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <SplitTile
            color={LEAD_COLOR}
            label={fill(t("costs_view.agents_lead_total"), { name: leadName })}
            value={money(leadUsd)}
            loading={loading}
          />
          <SplitTile
            color="var(--muted-foreground)"
            label={fill(t("costs_view.agents_all_total"), { count: formatExact(agentCount) })}
            value={money(agentsUsd)}
            loading={loading}
          />
        </div>
      </div>

      <div className="mt-3 pb-2">
        {!loading && rows.length === 0 ? (
          <div className="px-4 pb-2">
            <EmptyRow>{t("costs_view.agents_empty")}</EmptyRow>
          </div>
        ) : (
          <ul aria-label={t("costs_view.agents_list")} className="flex flex-col">
            {visible.map((row) => {
              const known = byId.get(row.key);
              const name = row.lead ? leadName : known?.name || agentDisplayName(row);
              const swatch = {
                agentId: row.key,
                name,
                tier: row.lead ? ("lead" as const) : ("specialist" as const),
                figure: known?.figure ?? null,
                palette: known?.palette ?? NO_PALETTE,
              };
              const isActive = active.includes(row.key);
              const width = maxUsd > 0 ? Math.max(2, Math.round((row.cost_usd / maxUsd) * 100)) : 2;
              return (
                <li key={row.key}>
                  <button
                    type="button"
                    onClick={() => onToggle(row.key)}
                    aria-pressed={isActive}
                    className={cn(
                      "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-4 py-3 text-left transition-colors hover:bg-sheen/[0.04] sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_7rem_6rem]",
                      isActive && "bg-sheen/[0.06]",
                      row.archived && "opacity-60",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <AgentSwatch agent={swatch} size={28} />
                      <span className="truncate text-sm font-medium text-foreground">{name}</span>
                    </span>
                    <span className="hidden h-2 w-full overflow-hidden rounded-full bg-sheen/[0.08] sm:block">
                      <span
                        className="block h-full rounded-full"
                        style={{
                          width: `${width}%`,
                          background: row.lead ? LEAD_COLOR : agentColor(swatch),
                        }}
                      />
                    </span>
                    <span className="text-right text-sm font-semibold tabular-nums text-foreground">
                      {money(row.cost_usd)}
                    </span>
                    <span
                      className="hidden text-right text-sm tabular-nums text-muted-foreground sm:block"
                      title={fill(t("costs_view.agents_tokens_exact"), { tokens: formatExact(row.tokens_total) })}
                    >
                      {formatTokensOrNone(row.tokens_total)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {ordered.length > FIRST_ROWS ? (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="mx-4 mt-1 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-sheen/[0.04] hover:text-foreground"
          >
            {showAll
              ? t("costs_view.agents_show_less")
              : fill(t("costs_view.agents_show_all"), { count: formatExact(ordered.length) })}
          </button>
        ) : null}
      </div>
    </Panel>
  );
}

function SplitTile({
  color,
  label,
  value,
  loading,
}: {
  color: string;
  label: string;
  value: string;
  loading?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-card/40 px-4 py-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-foreground-strong">
        {loading ? "…" : value}
      </div>
    </div>
  );
}
