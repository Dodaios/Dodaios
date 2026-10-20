/**
 * Every agent that owns a notebook folder, one card each: what it remembers
 * about its work and about the person, at a glance. Agents that were deleted
 * or that the roster never knew are folded away, and empty leftovers can be
 * archived in one step.
 */
import { useMemo, useState } from "react";
import { Bot, Brain, Sparkles, UserRound } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { MemoryAgent, MemoryIndex, MemoryPageSummary } from "@/lib/memoryApi";
import { countText, relativeAge, visibleAgents } from "@/lib/memoryModel";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";

export function AgentDirectory({
  index,
  language,
  onOpen,
  onTidy,
}: {
  index: MemoryIndex;
  language: string;
  onOpen: (path: string) => void;
  onTidy: () => void;
}) {
  const t = useT();
  const [showAll, setShowAll] = useState(false);
  const pagesByPath = useMemo(() => new Map(index.pages.map((page) => [page.path, page])), [index.pages]);
  const agents = visibleAgents(index.agents, showAll);
  const hidden = index.agents.length - visibleAgents(index.agents, false).length;
  const emptyLeftovers = index.agents.filter((agent) => agent.state !== "active" && agent.empty).length;

  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col px-8 pb-16 pt-8 lg:px-12" data-testid="memory-agents">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground-strong">{t("memory_view.area_agents")}</h2>
          <p className="mt-1 max-w-[560px] text-base text-muted-foreground">{t("memory_view.area_agents_hint")}</p>
        </div>
        {index.writable && emptyLeftovers > 0 && (
          <Button variant="outline" size="sm" onClick={onTidy} data-testid="memory-tidy">
            <Sparkles aria-hidden />
            {fill(t("memory_view.tidy_button"), { count: emptyLeftovers })}
          </Button>
        )}
      </header>

      {agents.length === 0 ? (
        <EmptyState icon={<Bot />} title={t("memory_view.agents_empty_title")} description={t("memory_view.agents_empty_body")} className="mt-10" />
      ) : (
        <ul className="mt-6 grid gap-3 md:grid-cols-2">
          {agents.map((agent) => (
            <li key={agent.agent_id}>
              <AgentCard agent={agent} pages={agent.pages.map((path) => pagesByPath.get(path)).filter(isPage)} language={language} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((value) => !value)}
          className="mt-5 self-start rounded-md px-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {showAll ? t("memory_view.agents_hide_inactive") : fill(t("memory_view.agents_show_inactive"), { count: hidden })}
        </button>
      )}
    </div>
  );
}

function isPage(page: MemoryPageSummary | undefined): page is MemoryPageSummary {
  return page !== undefined;
}

function AgentCard({
  agent,
  pages,
  language,
  onOpen,
}: {
  agent: MemoryAgent;
  pages: MemoryPageSummary[];
  language: string;
  onOpen: (path: string) => void;
}) {
  const t = useT();
  const memory = pages.find((page) => page.kind === "memory");
  const profile = pages.find((page) => page.kind === "profile");
  const notes = pages.filter((page) => page.kind === "note" && !page.empty).sort((a, b) => b.mtime - a.mtime);
  const first = memory && !memory.empty ? memory : profile && !profile.empty ? profile : notes[0] ?? memory ?? profile;
  return (
    <div
      className={cn(
        "flex h-full flex-col rounded-xl border border-border bg-background p-4 transition-colors",
        agent.state !== "active" && "bg-transparent",
      )}
    >
      <button type="button" onClick={() => first && onOpen(first.path)} className="flex items-center gap-3 text-left" disabled={!first}>
        <span
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-sm font-semibold uppercase",
            agent.state === "active" ? "bg-surface-raised text-foreground-strong" : "bg-secondary text-muted-foreground",
          )}
          aria-hidden
        >
          {agent.name.slice(0, 1)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-medium text-foreground-strong">{agent.name}</span>
          <span className="block text-xs text-muted-foreground">
            {agent.state === "active" ? fill(t("memory_view.updated"), { age: relativeAge(agent.updated, language) }) : t(`memory_view.agent_${agent.state}`)}
          </span>
        </span>
      </button>
      <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-sm leading-5 text-muted-foreground">
        {memory && !memory.empty ? memory.summary : profile && !profile.empty ? profile.summary : t("memory_view.agent_nothing_yet")}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {memory && <Chip onClick={() => onOpen(memory.path)} icon={<Brain aria-hidden />} label={t("memory_view.kind_memory")} empty={memory.empty} />}
        {profile && <Chip onClick={() => onOpen(profile.path)} icon={<UserRound aria-hidden />} label={t("memory_view.kind_profile")} empty={profile.empty} />}
        {notes.length > 0 && (
          <Chip onClick={() => onOpen(notes[0].path)} label={countText(t, "memory_view.notes_count", notes.length)} empty={false} />
        )}
      </div>
    </div>
  );
}

function Chip({ onClick, icon, label, empty }: { onClick: () => void; icon?: JSX.Element; label: string; empty: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs font-medium transition-colors [&>svg]:h-3.5 [&>svg]:w-3.5",
        empty
          ? "border-dashed border-border text-foreground-faint hover:text-muted-foreground"
          : "border-border text-foreground hover:bg-secondary",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
