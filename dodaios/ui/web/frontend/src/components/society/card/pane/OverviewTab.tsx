/**
 * The pane's Details tab, as a few calm cards: its instructions, what it
 * thinks with and how freely it may act, its routines with a switch each,
 * rows to everything else, and its record in one line. A short list of next
 * steps sits on top while there is something worth doing; each one can be
 * dismissed for good. Name and role are edited in the pane header.
 */
import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { useRunLocale } from "@/components/runs/format";
import { Switch } from "@/components/ui/switch";
import { useLocaleChunk, useT } from "@/i18n";
import { setTaskEnabled } from "@/lib/tasksApi";
import { stripInlineMarks } from "@/lib/plainMarks";
import { resolveToolBrand } from "@/lib/toolBrand";
import { useAgentChatStore } from "@/store/agentChat";

import { displayRoutineTitle, useAgentRoutines, useAgentSkills, type LiveRoutine } from "../../cardData";
import { useSocietyCapabilities, type SocietyAgent } from "../../data";
import { useSocietyChatStore } from "../../chat/AgentChatPanel";
import { AgentModelPicker } from "../../chat/AgentModelPicker";
import { ApprovalModePicker } from "../AgentHeader";
import { humanSchedule } from "../routines/humanSchedule";
import { useDismissedSuggestions, type PanePage, type PaneTab } from "./paneState";
import type { ReviewQueue } from "./reviewQueue";
import { AnatomyRow, PaneHint, PaneSection } from "./ui";

/**
 * The instructions as lines a person reads: a Markdown heading ("## How you
 * work") reads as its words in bold, inline marks drop, blank lines keep
 * their space.
 */
function instructionLines(text: string): { text: string; heading: boolean }[] {
  return text.replace(/\r\n?/g, "\n").split("\n").map((raw) => {
    const heading = /^\s{0,3}#{1,6}\s+/.test(raw);
    const words = stripInlineMarks(raw.replace(/^\s{0,3}#{1,6}\s+/, "").replace(/\s+#+\s*$/, ""));
    return { text: words, heading: heading && Boolean(words.trim()) };
  });
}

/** More lines than this and the instructions preview fades into "open to read all". */
const PREVIEW_LINES = 5;
const MAX_SUGGESTIONS = 3;
/** Routines listed with a switch; the Tasks tab has the rest. */
const MAX_ROUTINES = 5;

export interface OverviewTabProps {
  agent: SocietyAgent;
  sample: boolean;
  queue: ReviewQueue | undefined;
  onTab: (tab: PaneTab) => void;
  onPage: (page: PanePage) => void;
  /** Reports a model save in flight so the composer holds Send meanwhile. */
  onModelSavingChange?: (saving: boolean) => void;
}

interface Suggestion {
  id: string;
  text: string;
  go: () => void;
}

export function OverviewTab({ agent, sample, queue, onTab, onPage, onModelSavingChange }: OverviewTabProps) {
  const t = useT();
  useLocaleChunk("society");
  const locale = useRunLocale();
  const lead = agent.tier === "lead";
  const skills = useAgentSkills(sample ? null : agent.agentId);
  const routines = useAgentRoutines(sample ? null : agent.agentId);
  const capabilities = useSocietyCapabilities(!sample && !lead);
  const busy = useSocietyChatStore((state) => state.busy && state.activeSessionId === agent.chatSessionId);
  const [dismissed, dismiss] = useDismissedSuggestions(agent.agentId);
  const [expanded, setExpanded] = useState(false);

  const skillCount = skills.data?.length ?? 0;
  const routineRows = routines.data ?? [];
  const routineCount = sample ? agent.routines.length : routineRows.length;
  const pendingReview = queue?.total ?? 0;

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

  const perToken = agent.billedPerToken !== false;
  const capped = agent.dailyBudgetUsd > 0;
  const spent = agent.stats.spentTodayUsd;
  const share = capped ? Math.min(1, spent / agent.dailyBudgetUsd) : 0;
  const lastActive = agent.stats.lastActiveMs
    ? new Date(agent.stats.lastActiveMs).toLocaleDateString(locale, { day: "numeric", month: "short" })
    : t("society.card.never");

  return (
    <div className="ap-body" data-testid="agent-pane-overview">
      {visible.length > 0 ? (
        <div className="flex flex-col gap-2" data-testid="agent-pane-suggestions" aria-label={t("society.agent_pane.next_steps")}>
          {visible.map((s) => (
            <div key={s.id} className="ap-suggest" data-testid={`agent-pane-suggestion-${s.id.split(":")[0]}`}>
              <button type="button" className="ap-suggest-go" onClick={s.go}>
                {s.text}
              </button>
              <button
                type="button"
                className="ap-round-btn"
                data-size="sm"
                aria-label={t("society.agent_pane.dismiss")}
                title={t("society.agent_pane.dismiss")}
                onClick={() => dismiss(s.id)}
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      ) : null}

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
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            <span className="ap-instructions-text">
              {instructionLines(agent.description).map((line, i) => (
                <span key={i} className="ap-instructions-line" data-heading={line.heading || undefined}>{line.text}</span>
              ))}
            </span>
          </button>
        ) : (
          <PaneHint>{t("society.agent_pane.instructions_empty")}</PaneHint>
        )}
      </PaneSection>

      <PaneSection title={t("society.agent_pane.runs_on")} testId="agent-pane-seat">
        {lead ? (
          <LeadModelRow />
        ) : (
          <div className="ap-card">
            <AgentChatStoreProvider store={useSocietyChatStore}>
              <AgentModelPicker key={agent.agentId} agent={agent} busy={busy} onSavingChange={(saving) => onModelSavingChange?.(saving)}
                triggerClassName="ap-line" />
            </AgentChatStoreProvider>
            {!sample ? <ApprovalModePicker agent={agent} /> : null}
            <div className="ap-line" data-static="true">
              <span className="ap-line-label">{t("society.agent_pane.runtime")}</span>
              <span className="ap-line-value" title={t(`society.runtime.${agent.runtime ?? "jarvis"}_hint`)}>
                {t(`society.runtime.${agent.runtime ?? "jarvis"}`)}
                {agent.executionEnvironment === "sandbox" ? ` · ${t("society.sandbox.code")}` : ""}
              </span>
            </div>
          </div>
        )}
      </PaneSection>

      {sample || routineRows.length > 0 ? (
        <PaneSection
          title={t("society.agent_pane.routines")}
          testId="agent-pane-routines"
          action={routineCount > MAX_ROUTINES ? (
            <button type="button" className="ap-link" onClick={() => onTab("tasks")}>{t("society.agent_pane.see_all")}</button>
          ) : undefined}
        >
          {sample ? (
            <PaneHint>{agent.routines.length ? agent.routines.map((r) => r.label).join(", ") : t("society.agent_pane.routines_none")}</PaneHint>
          ) : (
            <div className="ap-card">
              {routineRows.slice(0, MAX_ROUTINES).map((routine) => (
                <RoutineSwitchRow key={routine.id} routine={routine} locale={locale} onOpen={() => onTab("tasks")}
                  onChanged={() => void routines.refetch()} />
              ))}
            </div>
          )}
        </PaneSection>
      ) : null}

      <PaneSection title={t("society.agent_pane.more")} testId="agent-pane-anatomy">
        <div className="ap-card">
          <AnatomyRow
            label={t("society.agent_pane.tab_tools")}
            detail={toolsDetail}
            attention={disconnected.length > 0}
            onOpen={() => onTab("tools")}
            testId="agent-pane-row-tools"
          />
          <AnatomyRow
            label={t("society.agent_pane.skills")}
            detail={skillCount ? (skills.data ?? []).map((s) => s.name).join(", ") : t("society.agent_pane.skills_none")}
            count={sample || !skillCount ? null : skillCount}
            onOpen={() => onPage({ id: "skills", title: t("society.agent_pane.skills") })}
            testId="agent-pane-row-skills"
          />
          <AnatomyRow
            label={t("society.agent_pane.files")}
            detail={agent.workspaceDir || `society/${agent.agentId}/`}
            onOpen={filesPage}
            testId="agent-pane-row-files"
          />
          {lead ? (
            <AnatomyRow
              label={t("society.agent_pane.tab_history")}
              detail={t("society.agent_pane.history_detail")}
              onOpen={() => onTab("history")}
              testId="agent-pane-row-history"
            />
          ) : null}
        </div>
      </PaneSection>

      <div className="ap-record" data-testid="agent-pane-record">
        <p>{recordLine(t, locale, agent, lastActive)}</p>
        {/* A subscription or local model spends nothing per run: no dollar lines. */}
        {perToken ? (
          <p>
            {t("society.card.meter_today")}:{" "}
            {capped
              ? t("society.card.spent_of").replace("{0}", spent.toFixed(2)).replace("{1}", agent.dailyBudgetUsd.toFixed(2))
              : `$${spent.toFixed(2)} · ${t("society.card.no_cap")}`}
          </p>
        ) : null}
        {perToken && capped ? (
          <div className="ap-meter" data-full={share >= 1 ? "true" : undefined} role="img" aria-label={`${t("society.card.meter_today")}: $${spent.toFixed(2)}`}>
            <span className="ap-meter-fill" style={{ width: `${Math.round(share * 100)}%` }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * "3 runs · $1.20 spent · last active 12 Oct": the money only where a
 * per-token key pays for the runs; a plan or a local model shows none.
 */
export function recordLine(
  t: (key: string) => string,
  locale: string,
  agent: Pick<SocietyAgent, "stats" | "billedPerToken">,
  lastActive: string,
): string {
  const runs = agent.stats.runs;
  const one = (() => {
    try {
      return new Intl.PluralRules(locale).select(runs) === "one";
    } catch {
      return runs === 1;
    }
  })();
  const parts = [t(one ? "society.agent_pane.record_runs_one" : "society.agent_pane.record_runs").replace("{0}", String(runs))];
  if (agent.billedPerToken !== false) {
    parts.push(t("society.agent_pane.record_spent").replace("{0}", `$${agent.stats.totalCostUsd.toFixed(2)}`));
  }
  parts.push(t("society.agent_pane.record_last_active").replace("{0}", lastActive));
  return parts.join(" · ");
}

/** The lead thinks with the app's own model choice; shown here, changed in its chat. */
function LeadModelRow() {
  const t = useT();
  const draft = useAgentChatStore((s) => s.draft);
  const providerById = useAgentChatStore((s) => s.providerById);
  const loadCatalog = useAgentChatStore((s) => s.loadCatalog);
  const catalog = useAgentChatStore((s) => s.catalog);
  const catalogStale = useAgentChatStore((s) => s.catalogStale);
  useEffect(() => {
    if (!catalog || catalogStale) void loadCatalog();
  }, [catalog, catalogStale, loadCatalog]);
  const provider = providerById(draft.provider);
  return (
    <>
      <div className="ap-card">
        <div className="ap-line" data-static="true">
          <span className="ap-line-label">{t("society.chat.model")}</span>
          <span className="ap-line-value">
            {[provider?.label ?? t("society.card.default_brain"), draft.model || t("society.chat.model_provider_default")].join(" · ")}
          </span>
        </div>
      </div>
      <PaneHint>{t("society.card.brain_shared_hint")}</PaneHint>
    </>
  );
}

const ROUTINE_ACTIVE = ["scheduled", "active", "enabled", ""];
const ROUTINE_TERMINAL = ["completed", "failed", "cancelled", "interrupted"];

/** One routine: its name and schedule, and a switch that pauses or resumes every part of it. */
function RoutineSwitchRow({ routine, locale, onOpen, onChanged }: {
  routine: LiveRoutine; locale: string; onOpen: () => void; onChanged: () => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const title = displayRoutineTitle(routine.title);
  const on = routine.state !== "paused";
  const canToggle = routine.state === "paused" || (ROUTINE_ACTIVE.includes(routine.state) && routine.state !== "running");
  const sentence = humanSchedule(routine.trigger, { t, locale }) || routine.schedule;
  const toggle = async (next: boolean) => {
    setBusy(true);
    setProblem("");
    try {
      for (const member of routine.members ?? [routine]) {
        if (ROUTINE_TERMINAL.includes(member.state)) continue;
        if ((member.state === "paused") === next) await setTaskEnabled(member.id, next);
      }
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      onChanged();
    }
  };
  return (
    <div className="ap-routine" data-testid={`agent-pane-routine-${routine.id}`}>
      <button type="button" className="min-w-0 flex-1 text-left" onClick={onOpen}>
        <span className="ap-row-label">{title}</span>
        <span className="ap-row-detail">{sentence}</span>
        {problem ? <span role="alert" className="ap-row-detail text-destructive">{problem}</span> : null}
      </button>
      <Switch
        checked={on}
        disabled={busy || !canToggle}
        onCheckedChange={(next) => void toggle(next)}
        aria-label={`${title}: ${t(on ? "society.agent_routines.list.pause" : "society.agent_routines.list.resume")}`}
      />
    </div>
  );
}
