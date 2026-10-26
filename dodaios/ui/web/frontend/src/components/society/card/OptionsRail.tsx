/**
 * The agent's home beside its chat: one details pane with the same anatomy
 * for every agent, in tabs that remember where the person was.
 *
 *  - Overview: identity (name, role, instructions edited in place), what it
 *    runs on, its six-part anatomy as counted rows, and a few next steps.
 *  - Tools & access: reach, tools, approvals and rules, limits, its browser
 *    and where it works, saved together; widening changes ask first.
 *  - Memory: its notebooks, learned rules and skills, plus the review queue
 *    of what it learned or proposed, with "Review in chat".
 *  - Tasks: its routines. Browser: its live screen. History: the lead's chats
 *    and calls.
 *
 * Drill-downs (instructions, a memory file, skills, files) open IN the pane
 * with a Back button instead of stacking a modal. Look and Share are header
 * actions; Pause and Retire live in the header's "…" menu. The file keeps its
 * historical name and export: the layout mounts `<OptionsRail …>`.
 */
import { lazy, Suspense, useEffect, useRef, useState, type CSSProperties } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import {
  ChevronLeft,
  History,
  LayoutGrid,
  Lightbulb,
  ListChecks,
  Monitor,
  MoreHorizontal,
  Palette,
  Pause,
  Play,
  Share2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { useLocaleChunk, useT } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { AgentSwatch } from "../AgentSwatch";
import { useSetAgentPaused, type SocietyAgent } from "../data";
import { DodaiosHistoryRail } from "../chat/DodaiosHistoryRail";
import { AgentBrowserPreview } from "./AgentBrowserPreview";
import { AgentRoutinesList } from "./AgentRoutinesList";
import { RetireButton } from "./RetireButton";
import { MemoryTab } from "./pane/MemoryTab";
import { OverviewTab } from "./pane/OverviewTab";
import { usePaneStack, usePaneTab, type PaneTab } from "./pane/paneState";
import { useReviewQueue } from "./pane/reviewQueue";
import { FilesPage, InstructionsPage, MemoryFilePage, SkillsPage } from "./pane/SubPages";
import { ToolsTab } from "./pane/ToolsTab";
import "./pane/agentPane.css";

const AgentAppearanceDialog = lazy(() => import("../companion/AgentAppearanceDialog").then(m => ({ default: m.AgentAppearanceDialog })));
const ShareAgentDialog = lazy(() => import("./ShareAgentDialog").then(m => ({ default: m.ShareAgentDialog })));

export interface OptionsRailProps {
  agent: SocietyAgent;
  onRetired: () => void;
  /** True when rows come from the sample roster rather than society.db. */
  sample?: boolean;
  /** The width the layout gives the pane, in px; the pane adapts its tab labels to it. */
  width?: number;
}

const TAB_ICONS: Record<PaneTab, LucideIcon> = {
  overview: LayoutGrid,
  tools: Wrench,
  memory: Lightbulb,
  tasks: ListChecks,
  browser: Monitor,
  history: History,
};

export function OptionsRail({ agent, onRetired, sample = false, width }: OptionsRailProps) {
  const t = useT();
  useLocaleChunk("society");
  const lead = agent.tier === "lead";
  const assistantName = useEventStore((s) => s.assistantName);
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

  return (
    <aside
      className="ap-root"
      aria-label={t("society.card.options")}
      data-testid="agent-card-options"
      data-width={width}
      style={{ "--ap-agent": agent.palette.primary } as CSSProperties}
    >
      <PaneHeader
        agent={agent}
        sample={sample}
        name={societyDisplayName(agent, assistantName)}
        onLook={() => setAppearanceOpen(true)}
        onShare={() => setShareOpen(true)}
        onRetired={onRetired}
      />
      <Tabs.Root value={tab} onValueChange={(value) => choose(value as PaneTab)} className="flex min-h-0 flex-1 flex-col">
        <Tabs.List className="ap-tabs" aria-label={t("society.agent_pane.tabs")}>
          {available.map((id) => {
            const Icon = TAB_ICONS[id];
            return (
              <Tabs.Trigger
                key={id}
                value={id}
                className="ap-tab"
                aria-label={tabLabel(id)}
                title={tabLabel(id)}
                data-testid={`agent-pane-tab-${id}`}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="ap-tab-label">{tabLabel(id)}</span>
                {id === "memory" && pending > 0 ? <span className="ap-tab-badge" aria-hidden /> : null}
              </Tabs.Trigger>
            );
          })}
        </Tabs.List>

        {page ? (
          <div className="ap-sub" data-testid="agent-pane-subpage">
            <button type="button" className="ap-icon-btn" onClick={stack.back} aria-label={t("society.agent_pane.back")} title={t("society.agent_pane.back")} data-testid="agent-pane-back">
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </button>
            <span className="truncate">{page.title}</span>
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
                <OverviewTab key={agent.agentId} agent={agent} sample={sample} queue={queue.data} onTab={choose} onPage={stack.push} />
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
}: {
  agent: SocietyAgent;
  sample: boolean;
  name: string;
  onLook: () => void;
  onShare: () => void;
  onRetired: () => void;
}) {
  const t = useT();
  const lead = agent.tier === "lead";
  const setPaused = useSetAgentPaused();
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
      <span className="ap-avatar">
        <AgentSwatch agent={agent} size={30} />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="ap-name" title={name}>{name}</h2>
        <div className="ap-meta">
          <span className="ap-dot" data-state={agent.state} aria-hidden />
          <span className="shrink-0">{t(`society.state.${agent.state}`)}</span>
          {agent.title && agent.title !== name ? <span className="truncate">· {agent.title}</span> : null}
        </div>
      </div>
      <button type="button" className="ap-icon-btn" onClick={onLook} aria-label={t("society.companion.appearance")} title={t("society.companion.appearance")} data-testid="edit-agent-appearance">
        <Palette className="h-4 w-4" aria-hidden />
      </button>
      {/* The lead is every install's own assistant and sample rows are not real agents: neither is shareable. */}
      {!lead && !sample ? (
        <button type="button" className="ap-icon-btn" onClick={onShare} aria-label={t("society.share.cta")} title={t("society.share.cta_hint")} data-testid="share-agent">
          <Share2 className="h-4 w-4" aria-hidden />
        </button>
      ) : null}
      <div ref={moreRef} className="relative">
        <button
          ref={triggerRef}
          type="button"
          className="ap-icon-btn"
          aria-label={t("society.card.options_more")}
          aria-expanded={more}
          aria-haspopup="menu"
          onClick={() => setMore((v) => !v)}
          data-testid="agent-card-options-more"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </button>
        {more ? (
          <div role="menu" className="ap-menu shadow-float">
            {!lead ? (
              <>
                <button type="button" role="menuitem" className="ap-menu-item" disabled={busy} onClick={() => void togglePause()} data-testid="agent-pane-pause">
                  {paused ? <Play className="h-3.5 w-3.5" aria-hidden /> : <Pause className="h-3.5 w-3.5" aria-hidden />}
                  {paused ? t("society.card.action_resume") : t("society.card.action_pause")}
                </button>
                <div className="ap-menu-sep" role="separator" />
              </>
            ) : null}
            <div className="p-2">
              <RetireButton agent={agent} onRetired={onRetired} variant="rail" />
            </div>
          </div>
        ) : null}
      </div>
    </header>
  );
}

export default OptionsRail;
