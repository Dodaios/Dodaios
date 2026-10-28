/**
 * The agent's home beside its chat: one details pane with the same anatomy
 * for every agent. It is closed until the person opens it from the name pill
 * in the chat header.
 *
 * On top: the agent's face and name, large and centred, with "…" (look,
 * share, pause, retire) and close as two round buttons. Below: four tabs as
 * plain words that remember where the person was.
 *
 *  - Details: name and role, instructions, its model and permissions, its
 *    routines with a switch each, a few rows to everything else, and a
 *    one-line record.
 *  - Memory: its notebooks, learned rules and skills, plus the review queue.
 *  - Tasks: its routines in full. Computer: its live browser screen.
 *
 * Tools & access (and the lead's History) open from rows in Details as a
 * page with a way back; they stay mounted once visited so unsaved access
 * edits survive. Drill-downs (instructions, a memory file, skills, files)
 * open in the pane the same way. The file keeps its historical name and
 * export: the layout mounts `<OptionsRail …>`.
 */
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { ChevronLeft, MoreHorizontal, X } from "lucide-react";

import { useLocaleChunk, useT } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { AgentSwatch } from "../AgentSwatch";
import { useSetAgentPaused, useUpdateAgentConfig, type SocietyAgent } from "../data";
import { DodaiosHistoryRail } from "../chat/DodaiosHistoryRail";
import { AgentBrowserPreview } from "./AgentBrowserPreview";
import { useDetailsPane } from "./AgentChatLayout";
import { AgentRoutinesList } from "./AgentRoutinesList";
import { RetireButton } from "./RetireButton";
import { MemoryTab } from "./pane/MemoryTab";
import { OverviewTab } from "./pane/OverviewTab";
import { usePaneStack, usePaneTab, type PaneTab } from "./pane/paneState";
import { useReviewQueue } from "./pane/reviewQueue";
import { FilesPage, InstructionsPage, MemoryFilePage, SkillsPage } from "./pane/SubPages";
import { InlineEdit } from "./pane/ui";
import { ToolsTab } from "./pane/ToolsTab";
import "./pane/agentPane.css";

const AgentAppearanceDialog = lazy(() => import("../companion/AgentAppearanceDialog").then(m => ({ default: m.AgentAppearanceDialog })));
const ShareAgentDialog = lazy(() => import("./ShareAgentDialog").then(m => ({ default: m.ShareAgentDialog })));

export interface OptionsRailProps {
  agent: SocietyAgent;
  onRetired: () => void;
  /** True when rows come from the sample roster rather than society.db. */
  sample?: boolean;
  /** The width the layout gives the pane, in px. */
  width?: number;
  /** Reports a model save from the Details tab, so the composer holds Send meanwhile. */
  onModelSavingChange?: (saving: boolean) => void;
}

/** The tabs shown as words; the others open from rows in Details. */
const PRIMARY_TABS: readonly PaneTab[] = ["overview", "memory", "tasks", "browser"];

export function OptionsRail({ agent, onRetired, sample = false, width, onModelSavingChange }: OptionsRailProps) {
  const t = useT();
  useLocaleChunk("society");
  const lead = agent.tier === "lead";
  const assistantName = useEventStore((s) => s.assistantName);
  const pane = useDetailsPane();
  const available: PaneTab[] = lead
    ? ["overview", "tools", "memory", "tasks", "browser", "history"]
    : ["overview", "tools", "memory", "tasks", "browser"];
  const [tab, setTab] = usePaneTab(available);
  const stack = usePaneStack();
  const [visited, setVisited] = useState<Set<PaneTab>>(() => new Set([tab]));
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const queue = useReviewQueue(agent.agentId, !sample);
  // Only real decisions (a proposal, a share request) mark the tab; the
  // agent's routine notebook writes wait quietly in the list.
  const pending = (queue.data?.counts?.proposal ?? 0) + (queue.data?.counts?.memory_share ?? 0);
  const { reset } = stack;
  const name = societyDisplayName(agent, assistantName);

  useEffect(() => {
    setAppearanceOpen(false);
    setShareOpen(false);
    reset();
  }, [agent.agentId, reset]);

  useEffect(() => {
    setVisited((prev) => (prev.has(tab) ? prev : new Set([...prev, tab])));
  }, [tab]);

  const choose = (next: PaneTab) => {
    stack.reset();
    setTab(next);
  };

  const page = stack.page;
  const tabLabel = (id: PaneTab) => t(`society.agent_pane.tab_${id}`);
  const secondary = !PRIMARY_TABS.includes(tab);

  return (
    <aside
      className="ap-root"
      aria-label={t("society.card.options")}
      data-testid="agent-card-options"
      data-width={width}
    >
      <PaneHeader
        agent={agent}
        sample={sample}
        name={name}
        onLook={() => setAppearanceOpen(true)}
        onShare={() => setShareOpen(true)}
        onRetired={onRetired}
        onClose={pane?.close}
      />
      <Tabs.Root value={tab} onValueChange={(value) => choose(value as PaneTab)} className="flex min-h-0 flex-1 flex-col">
        <Tabs.List className="ap-tabs" aria-label={t("society.agent_pane.tabs")}>
          {PRIMARY_TABS.map((id) => (
            // Radix selects on pointer-down; a plain click (keyboard activation, element.click()) selects too.
            <Tabs.Trigger key={id} value={id} className="ap-tab" data-testid={`agent-pane-tab-${id}`}
              onClick={() => { if (id !== tab) choose(id); }}>
              {tabLabel(id)}
              {id === "memory" && pending > 0 ? <span className="ap-tab-badge" aria-hidden /> : null}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {page || secondary ? (
          <div className="ap-sub" data-testid="agent-pane-subpage">
            <button
              type="button"
              className="ap-icon-btn"
              onClick={page ? stack.back : () => choose("overview")}
              aria-label={t("society.agent_pane.back")}
              title={t("society.agent_pane.back")}
              data-testid="agent-pane-back"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </button>
            <span className="truncate">{page ? page.title : tabLabel(tab)}</span>
          </div>
        ) : null}
        {page ? (
          <div key={`${agent.agentId}:${page.id}`} className="flex min-h-0 flex-1 flex-col">
            {page.id === "instructions" ? <InstructionsPage agent={agent} sample={sample} />
              : page.id === "skills" ? <SkillsPage agent={agent} sample={sample} />
              : page.id === "files" ? <FilesPage agent={agent} />
              : page.id.startsWith("file:") ? <MemoryFilePage agent={agent} path={page.id.slice(5)} />
              : null}
          </div>
        ) : null}

        {available.map((id) => {
          const active = id === tab && !page;
          // A visited tab keeps its state (a routine draft, unsaved access
          // edits) while hidden; the live browser stream runs only on screen.
          const mounted = id === "browser" ? active : visited.has(id) || id === tab;
          if (!mounted) return null;
          return (
            <Tabs.Content
              key={id}
              value={id}
              forceMount
              hidden={!active}
              className={cn("min-h-0 flex-1 flex-col outline-none", active ? "flex" : "hidden")}
            >
              {id === "overview" ? (
                <OverviewTab key={agent.agentId} agent={agent} sample={sample} queue={queue.data} onTab={choose} onPage={stack.push}
                  onModelSavingChange={onModelSavingChange} />
              ) : id === "tools" ? (
                <ToolsTab key={agent.agentId} agent={agent} sample={sample} />
              ) : id === "memory" ? (
                <MemoryTab key={agent.agentId} agent={agent} sample={sample} queue={queue.data} queueLoading={queue.isLoading} onPage={stack.push} />
              ) : id === "tasks" ? (
                <div className="ap-body" data-fill="true">
                  <AgentRoutinesList
                    key={agent.agentId}
                    agentId={agent.agentId}
                    sampleRoutines={sample ? agent.routines : undefined}
                    variant="rail"
                    className="min-h-48 flex-1"
                  />
                </div>
              ) : id === "browser" ? (
                <div className="ap-body" data-fill="true">
                  <AgentBrowserPreview agent={agent} />
                </div>
              ) : (
                <div className="ap-body" data-fill="true">
                  <DodaiosHistoryRail />
                </div>
              )}
            </Tabs.Content>
          );
        })}
      </Tabs.Root>
      {appearanceOpen && <Suspense fallback={null}><AgentAppearanceDialog key={agent.agentId} agent={agent} sample={sample} onClose={() => setAppearanceOpen(false)} /></Suspense>}
      {shareOpen && <Suspense fallback={null}><ShareAgentDialog key={agent.agentId} agent={agent} onClose={() => setShareOpen(false)} /></Suspense>}
    </aside>
  );
}

function PaneHeader({
  agent,
  sample,
  name,
  onLook,
  onShare,
  onRetired,
  onClose,
}: {
  agent: SocietyAgent;
  sample: boolean;
  name: string;
  onLook: () => void;
  onShare: () => void;
  onRetired: () => void;
  onClose?: () => void;
}) {
  const t = useT();
  const lead = agent.tier === "lead";
  const setPaused = useSetAgentPaused();
  const update = useUpdateAgentConfig();
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const paused = agent.lifecycle === "paused" || agent.state === "paused";

  useEffect(() => setMore(false), [agent.agentId]);
  useEffect(() => {
    if (!more) return;
    // Keyboard users land on the first action, as a menu should.
    moreRef.current?.querySelector<HTMLElement>('[role="menu"] button:not(:disabled)')?.focus();
    const onDown = (e: MouseEvent) => {
      if (!moreRef.current?.contains(e.target as Node)) setMore(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMore(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [more]);

  const togglePause = async () => {
    setBusy(true);
    try {
      await setPaused(agent, !paused);
    } finally {
      setBusy(false);
      setMore(false);
    }
  };

  return (
    <header className="ap-head">
      <div className="ap-head-actions">
        <div ref={moreRef} className="relative">
          <button
            ref={triggerRef}
            type="button"
            className="ap-round-btn"
            aria-label={t("society.card.options_more")}
            title={t("society.card.options_more")}
            aria-expanded={more}
            aria-haspopup="menu"
            onClick={() => setMore((v) => !v)}
            data-testid="agent-card-options-more"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </button>
          {more ? (
            <div role="menu" className="ap-menu shadow-float">
              <button type="button" role="menuitem" className="ap-menu-item" data-testid="edit-agent-appearance"
                onClick={() => { setMore(false); onLook(); }}>
                {t("society.companion.appearance")}
              </button>
              {/* The lead is every install's own assistant and sample rows are not real agents: neither is shareable. */}
              {!lead && !sample ? (
                <button type="button" role="menuitem" className="ap-menu-item" data-testid="share-agent" title={t("society.share.cta_hint")}
                  onClick={() => { setMore(false); onShare(); }}>
                  {t("society.share.cta")}
                </button>
              ) : null}
              {!lead ? (
                <button type="button" role="menuitem" className="ap-menu-item" disabled={busy} onClick={() => void togglePause()} data-testid="agent-pane-pause">
                  {paused ? t("society.card.action_resume") : t("society.card.action_pause")}
                </button>
              ) : null}
              <div className="ap-menu-sep" role="separator" />
              <RetireButton agent={agent} onRetired={onRetired} variant="menu" />
            </div>
          ) : null}
        </div>
        {onClose ? (
          <button type="button" className="ap-round-btn" onClick={onClose} aria-label={t("society.agent_pane.close")}
            title={t("society.agent_pane.close")} data-testid="agent-pane-close">
            <X className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>
      <span className="ap-avatar">
        <AgentSwatch agent={agent} size={72} />
      </span>
      {/* Name and role are edited in place, right where they are read. */}
      <h2 className="ap-name" title={lead ? t("society.agent_pane.lead_name_hint") : name}>
        {lead || sample ? name : (
          <InlineEdit
            value={agent.name}
            label={t("society.agent_pane.rename")}
            maxLength={40}
            className="ap-head-edit"
            testId="agent-pane-name"
            onSave={async (next) => {
              if (!next) throw new Error(t("society.agent_pane.name_required"));
              await update(agent, { name: next });
            }}
          />
        )}
      </h2>
      <div className="ap-meta">
        {paused ? <span className="block">{t("society.state.paused")}</span> : null}
        {sample || lead ? (agent.title && agent.title !== name ? <span>{agent.title}</span> : null) : <InlineEdit
          value={agent.title}
          label={t("society.agent_pane.edit_role")}
          placeholder={t("society.agent_pane.role_placeholder")}
          maxLength={120}
          className="ap-head-edit"
          testId="agent-pane-role"
          onSave={async (title) => {
            await update(agent, { title });
          }}
        />}
      </div>
    </header>
  );
}

export default OptionsRail;
