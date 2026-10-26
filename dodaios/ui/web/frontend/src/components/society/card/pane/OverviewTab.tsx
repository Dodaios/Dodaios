/**
 * The pane's first tab: who this agent is, what it runs on, and its anatomy
 * in six counted rows that each open where that part is managed. A short list
 * of next steps sits on top while there is something worth doing; each one
 * can be dismissed for good.
 */
import { useMemo, useState } from "react";
import {
  BookOpen,
  CalendarClock,
  FolderOpen,
  Lightbulb,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";

import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { useRunLocale } from "@/components/runs/format";
import { useLocaleChunk, useT } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { resolveToolBrand } from "@/lib/toolBrand";
import { useEventStore } from "@/store/events";

import { RuntimeMark } from "../../RuntimeBadge";
import { useAgentRoutines, useAgentSkills } from "../../cardData";
import { useSocietyCapabilities, useUpdateAgentConfig, type SocietyAgent } from "../../data";
import { useAgentKnowledge } from "../AgentKnowledge";
import { LeadBrain } from "../LeadSections";
import { useDismissedSuggestions, type PanePage, type PaneTab } from "./paneState";
import type { ReviewQueue } from "./reviewQueue";
import { AnatomyRow, InlineEdit, PaneHint, PaneSection } from "./ui";

/** More lines than this and the instructions preview fades into "open to read all". */
const PREVIEW_LINES = 5;
const MAX_SUGGESTIONS = 3;

export interface OverviewTabProps {
  agent: SocietyAgent;
  sample: boolean;
  queue: ReviewQueue | undefined;
  onTab: (tab: PaneTab) => void;
  onPage: (page: PanePage) => void;
}

interface Suggestion {
  id: string;
  text: string;
  go: () => void;
}

export function OverviewTab({ agent, sample, queue, onTab, onPage }: OverviewTabProps) {
  const t = useT();
  useLocaleChunk("society");
  const locale = useRunLocale();
  const lead = agent.tier === "lead";
  const assistantName = useEventStore((s) => s.assistantName);
  const update = useUpdateAgentConfig();
  const knowledge = useAgentKnowledge(agent.agentId, sample);
  const skills = useAgentSkills(sample ? null : agent.agentId);
  const routines = useAgentRoutines(sample ? null : agent.agentId);
  const capabilities = useSocietyCapabilities(!sample && !lead);
  const [dismissed, dismiss] = useDismissedSuggestions(agent.agentId);
  const [expanded, setExpanded] = useState(false);

  const memoryFiles = (knowledge.data?.files ?? []).filter((f) => f.kind === "memory");
  const learnedRules = knowledge.data?.learned_instructions ?? [];
  const skillCount = skills.data?.length ?? 0;
  const routineRows = routines.data ?? [];
  const routineCount = sample ? agent.routines.length : routineRows.length;
  const nextRun = routineRows.map((r) => r.dueMs).filter((ms): ms is number => typeof ms === "number").sort((a, b) => a - b)[0];
  const pendingReview = queue?.total ?? 0;
  // Proposals and share requests are decisions; notebook writes are not.
  const decisions = (queue?.counts?.proposal ?? 0) + (queue?.counts?.memory_share ?? 0);

  const byId = useMemo(() => new Map((capabilities.data ?? []).map((c) => [c.id, c])), [capabilities.data]);
  const disconnected = agent.focus.filter((id) => byId.get(id)?.connected === false);

  const descriptionLines = agent.description.split(/\r?\n/).filter((line) => line.trim());
  const long = descriptionLines.length > PREVIEW_LINES || agent.description.length > 420;

  const instructionsPage = () => onPage({ id: "instructions", title: t("society.agent_pane.instructions") });
  const filesPage = () => onPage({ id: "files", title: t("society.agent_pane.files") });

  const suggestions: Suggestion[] = [];
  if (pendingReview > 0) {
    // Keyed by the count: dismissing it holds until something new arrives,
    // so a busy notebook never turns into a standing nag.
    suggestions.push({
      id: `review:${pendingReview}`,
      text: t("society.agent_pane.suggest_review").replace("{0}", String(pendingReview)),
      go: () => onTab("memory"),
    });
  }
  if (!lead && !agent.description.trim()) {
    suggestions.push({ id: "instructions", text: t("society.agent_pane.suggest_instructions"), go: instructionsPage });
  }
  if (!lead && disconnected.length > 0) {
    suggestions.push({
      id: "connect",
      text: t("society.agent_pane.suggest_connect").replace(
        "{0}",
        disconnected.map((id) => resolveToolBrand(byId.get(id)?.tool_name || id.replace(/^[a-z]+:/, "")).label).join(", "),
      ),
      go: () => onTab("tools"),
    });
  }
  if (!sample && routines.isSuccess && routineCount === 0) {
    suggestions.push({ id: "routine", text: t("society.agent_pane.suggest_routine"), go: () => onTab("tasks") });
  }
  const visible = suggestions.filter((s) => !dismissed.has(s.id)).slice(0, MAX_SUGGESTIONS);

  const toolsDetail = lead
    ? t("society.card.tools_all")
    : agent.focus.length
      ? agent.focus.map((id) => resolveToolBrand(byId.get(id)?.tool_name || id.replace(/^(plugin|cli|mcp|skill|core):/, "")).label).join(", ")
      : agent.grantMode === "allowlist"
        ? t("society.agent_pane.tools_allowlist_detail").replace("{0}", String(agent.toolGrants.length))
        : t("society.agent_pane.tools_all_detail");

  const capped = agent.dailyBudgetUsd > 0;
  const spent = agent.stats.spentTodayUsd;
  const share = capped ? Math.min(1, spent / agent.dailyBudgetUsd) : 0;
  const lastActive = agent.stats.lastActiveMs
    ? new Date(agent.stats.lastActiveMs).toLocaleDateString(locale, { day: "2-digit", month: "short" })
    : t("society.card.never");

  return (
    <div className="ap-body" data-testid="agent-pane-overview">
      {visible.length > 0 ? (
        <PaneSection title={t("society.agent_pane.next_steps")} testId="agent-pane-suggestions">
          <div className="flex flex-col gap-1.5">
            {visible.map((s) => (
              <div key={s.id} className="ap-suggest" data-testid={`agent-pane-suggestion-${s.id.split(":")[0]}`}>
                <button type="button" className="ap-suggest-go" onClick={s.go}>
                  {s.text}
                </button>
                <button
                  type="button"
                  className="ap-icon-btn h-6 w-6"
                  aria-label={t("society.agent_pane.dismiss")}
                  title={t("society.agent_pane.dismiss")}
                  onClick={() => dismiss(s.id)}
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </div>
            ))}
          </div>
        </PaneSection>
      ) : null}

      <PaneSection title={t("society.agent_pane.identity")}>
        <div className="flex flex-col gap-1.5">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="w-14 shrink-0 truncate text-xs text-muted-foreground">{t("society.profile_card.name")}</span>
            {lead ? (
              <span className="truncate text-sm font-medium" title={t("society.agent_pane.lead_name_hint")}>
                {societyDisplayName(agent, assistantName)}
              </span>
            ) : (
              <InlineEdit
                value={agent.name}
                label={t("society.agent_pane.rename")}
                maxLength={40}
                disabled={sample}
                className="text-sm font-medium"
                testId="agent-pane-name"
                onSave={async (name) => {
                  if (!name) throw new Error(t("society.agent_pane.name_required"));
                  await update(agent, { name });
                }}
              />
            )}
          </div>
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="w-14 shrink-0 truncate text-xs text-muted-foreground">{t("society.agent_pane.role")}</span>
            <InlineEdit
              value={agent.title}
              label={t("society.agent_pane.edit_role")}
              placeholder={t("society.agent_pane.role_placeholder")}
              maxLength={120}
              disabled={sample || lead}
              className="text-sm"
              testId="agent-pane-role"
              onSave={async (title) => {
                await update(agent, { title });
              }}
            />
          </div>
        </div>
      </PaneSection>

      <PaneSection
        title={t("society.agent_pane.instructions")}
        action={
          <button type="button" className="ap-link" onClick={instructionsPage} data-testid="agent-pane-edit-instructions">
            {t(lead || sample ? "society.agent_pane.open" : "society.card.edit")}
          </button>
        }
      >
        {lead ? (
          <PaneHint>{t("society.card.instructions_hint")}</PaneHint>
        ) : agent.description.trim() ? (
          <button
            type="button"
            className="ap-instructions text-left"
            data-long={long && !expanded ? "true" : undefined}
            style={expanded ? { maxHeight: "none" } : undefined}
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {agent.description}
          </button>
        ) : (
          <PaneHint>{t("society.agent_pane.instructions_empty")}</PaneHint>
        )}
      </PaneSection>

      <PaneSection title={t("society.agent_pane.runs_on")}>
        {lead ? (
          <LeadBrain />
        ) : (
          <div className="ap-seat" data-testid="agent-pane-seat">
            <span className="ap-seat-pill" title={t(`society.runtime.${agent.runtime ?? "jarvis"}_hint`)}>
              <RuntimeMark runtime={agent.runtime ?? "jarvis"} label={t(`society.runtime.${agent.runtime ?? "jarvis"}`)} />
              <span className="truncate">{t(`society.runtime.${agent.runtime ?? "jarvis"}`)}</span>
            </span>
            {agent.provider ? (
              <span className="ap-seat-pill">
                <ProviderLogo providerId={agent.provider} label={agent.providerLabel || agent.provider} size="sm" />
                <span className="truncate">{agent.providerLabel || agent.provider}</span>
              </span>
            ) : (
              <span className="ap-seat-pill px-2">{t("society.card.default_brain")}</span>
            )}
            {agent.model ? <span className="truncate font-mono text-[11px]">{agent.model}</span> : null}
            {agent.effort ? <span>· {agent.effort}</span> : null}
            {agent.executionEnvironment === "sandbox" ? <span>· {t("society.sandbox.code")}</span> : null}
          </div>
        )}
        {lead ? null : <PaneHint>{t("society.agent_pane.seat_hint")}</PaneHint>}
      </PaneSection>

      <PaneSection title={t("society.agent_pane.anatomy")} testId="agent-pane-anatomy">
        <div className="ap-rows">
          <AnatomyRow
            icon={BookOpen}
            label={t("society.agent_pane.instructions")}
            detail={
              learnedRules.length
                ? t("society.agent_pane.instructions_learned").replace("{0}", String(learnedRules.length))
                : agent.description.trim() || lead
                  ? t("society.agent_pane.instructions_written")
                  : t("society.agent_pane.instructions_none")
            }
            onOpen={instructionsPage}
            testId="agent-pane-row-instructions"
          />
          <AnatomyRow
            icon={Lightbulb}
            label={t("society.agent_pane.memory")}
            detail={
              pendingReview
                ? t("society.agent_pane.memory_waiting").replace("{0}", String(pendingReview))
                : t("society.agent_pane.memory_detail")
            }
            count={sample ? null : pendingReview > 0 ? pendingReview : memoryFiles.length}
            attention={decisions > 0}
            onOpen={() => onTab("memory")}
            testId="agent-pane-row-memory"
          />
          <AnatomyRow
            icon={Sparkles}
            label={t("society.agent_pane.skills")}
            detail={skillCount ? (skills.data ?? []).map((s) => s.name).join(", ") : t("society.agent_pane.skills_none")}
            count={sample ? null : skillCount}
            onOpen={() => onPage({ id: "skills", title: t("society.agent_pane.skills") })}
            testId="agent-pane-row-skills"
          />
          <AnatomyRow
            icon={CalendarClock}
            label={t("society.agent_pane.routines")}
            detail={
              nextRun
                ? t("society.agent_pane.routines_next").replace(
                    "{0}",
                    new Date(nextRun).toLocaleString(locale, { weekday: "short", hour: "2-digit", minute: "2-digit" }),
                  )
                : routineCount
                  ? t("society.agent_pane.routines_idle")
                  : t("society.agent_pane.routines_none")
            }
            count={routineCount}
            onOpen={() => onTab("tasks")}
            testId="agent-pane-row-routines"
          />
          <AnatomyRow
            icon={Wrench}
            label={t("society.agent_pane.tools")}
            detail={toolsDetail}
            count={lead ? null : agent.focus.length || null}
            attention={disconnected.length > 0}
            onOpen={() => onTab("tools")}
            testId="agent-pane-row-tools"
          />
          <AnatomyRow
            icon={FolderOpen}
            label={t("society.agent_pane.files")}
            detail={agent.workspaceDir || `society/${agent.agentId}/`}
            onOpen={filesPage}
            testId="agent-pane-row-files"
          />
        </div>
      </PaneSection>

      <PaneSection title={t("society.card.record")}>
        <div className="ap-stats">
          <div className="ap-stat">
            <span className="ap-stat-label">{t("society.card.runs")}</span>
            <span className="ap-stat-value">{agent.stats.runs}</span>
          </div>
          <div className="ap-stat">
            <span className="ap-stat-label">{t("society.card.cost")}</span>
            <span className="ap-stat-value">${agent.stats.totalCostUsd.toFixed(2)}</span>
          </div>
          <div className="ap-stat">
            <span className="ap-stat-label">{t("society.card.last_active")}</span>
            <span className="ap-stat-value">{lastActive}</span>
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{t("society.card.meter_today")}</span>
          <span className="tabular-nums">
            {capped
              ? t("society.card.spent_of").replace("{0}", spent.toFixed(2)).replace("{1}", agent.dailyBudgetUsd.toFixed(2))
              : `$${spent.toFixed(2)} · ${t("society.card.no_cap")}`}
          </span>
        </div>
        {capped ? (
          <div className="ap-meter" data-full={share >= 1 ? "true" : undefined} role="img" aria-label={`${t("society.card.meter_today")}: $${spent.toFixed(2)}`}>
            <span className="ap-meter-fill" style={{ width: `${Math.round(share * 100)}%` }} />
          </div>
        ) : null}
      </PaneSection>
    </div>
  );
}
