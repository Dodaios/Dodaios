/**
 * The thread sidebar's search: a floating window over the threads, not
 * the app-wide quick switcher. Empty, it lists the newest threads; typed into,
 * it matches thread titles and project names at once and, a moment later, the
 * messages of every thread (`/api/agent-chat/sessions/search`), each hit with
 * the line that matched. Enter opens the thread in the main column.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { searchAgentChatSessions, type ChatSearchHit } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { useTeamThreads } from "@/lib/teamThreadsApi";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { SearchThreadsIcon, TeamThreadIcon } from "./ThreadStartIcons";
import { projectIdFor, shortAge, threadTitle, useThreadChatStore } from "./threadModel";

/** Rows the empty search shows: the newest threads. */
const RECENT = 12;
/** How long typing rests before the messages are searched. */
const DEBOUNCE_MS = 160;

interface Row {
  key: string;
  kind: "thread" | "team";
  id: string;
  projectId: string;
  title: string;
  project: string;
  updated: number;
  provider: string;
  snippet: string;
  matches: number;
}

/** `text` with every caseless occurrence of `needle` marked. */
function Marked({ text, needle }: { text: string; needle: string }) {
  if (!needle) return <>{text}</>;
  const folded = text.toLowerCase();
  const target = needle.toLowerCase();
  const parts: ReactNode[] = [];
  let at = 0;
  for (let next = folded.indexOf(target); next >= 0 && target; next = folded.indexOf(target, at)) {
    if (next > at) parts.push(text.slice(at, next));
    parts.push(<mark key={next} className="rounded-sm bg-accent/25 text-foreground">{text.slice(next, next + target.length)}</mark>);
    at = next + target.length;
  }
  parts.push(text.slice(at));
  return <>{parts}</>;
}

export function ThreadSearch({ open, onClose, projects, onOpened }: {
  open: boolean;
  onClose: () => void;
  /** The projects the sidebar shows; a thread outside all of them is not listed. */
  projects: readonly IdeProject[];
  /** After a thread opened: the sidebar unfolds its project. */
  onOpened?: (projectId: string) => void;
}) {
  const t = useT();
  const sessions = useThreadChatStore((state) => state.sessions);
  const catalog = useThreadChatStore((state) => state.catalog);
  const projectOf = useIdeThreadsStore((state) => state.projectOf);
  const openThread = useIdeThreadsStore((state) => state.openThread);
  const openTeam = useIdeThreadsStore((state) => state.openTeam);
  const teams = useTeamThreads().data;
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [hits, setHits] = useState<{ query: string; rows: ChatSearchHit[] } | null>(null);
  const needle = query.trim().replace(/\s+/g, " ");

  useEffect(() => { if (!open) { setQuery(""); setHits(null); } }, [open]);

  // The messages are searched on the server once typing rests.
  useEffect(() => {
    if (!open || !needle) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchAgentChatSessions(needle, { signal: controller.signal })
        .then((rows) => setHits({ query: needle, rows }))
        .catch(() => { if (!controller.signal.aborted) setHits({ query: needle, rows: [] }); });
    }, DEBOUNCE_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, needle]);

  const agentOf = useMemo(() => {
    const map = new Map<string, { agent: string; label: string }>();
    for (const provider of catalog?.providers ?? []) {
      if (provider.agent) map.set(provider.id, { agent: provider.agent, label: provider.label });
    }
    return map;
  }, [catalog]);

  const rows = useMemo<Row[]>(() => {
    const projectName = new Map(projects.map((project) => [project.id, project.name]));
    const byId = new Map(sessions.map((session) => [session.session_id, session]));
    const out = new Map<string, Row>();
    const fold = needle.toLowerCase();
    const add = (row: Row) => { if (!out.has(row.key)) out.set(row.key, row); };
    const threadRow = (sessionId: string, cwd: string, fallback: { title: string; updated: number; provider: string }, extra?: Partial<Row>): Row | null => {
      const session = byId.get(sessionId);
      if (session?.team_id) return null;
      const projectId = projectIdFor({ session_id: sessionId, cwd: session?.cwd ?? cwd }, projects, projectOf);
      if (!projectId) return null;
      return {
        key: `thread:${sessionId}`, kind: "thread", id: sessionId, projectId,
        title: session ? threadTitle(session) : threadTitle({ title: fallback.title }),
        project: projectName.get(projectId) ?? "",
        updated: session?.updated_ms ?? fallback.updated,
        provider: session?.provider ?? fallback.provider,
        snippet: "", matches: 0, ...extra,
      };
    };
    const threads = sessions.filter((session) => !session.team_id);
    if (!fold) {
      for (const session of [...threads].sort((a, b) => b.updated_ms - a.updated_ms)) {
        const row = threadRow(session.session_id, session.cwd, { title: session.title, updated: session.updated_ms, provider: session.provider });
        if (row) add(row);
        if (out.size >= RECENT) break;
      }
      return [...out.values()];
    }
    // Titles and project names first: they match on the spot.
    const named: Row[] = [];
    for (const session of threads) {
      const row = threadRow(session.session_id, session.cwd, { title: session.title, updated: session.updated_ms, provider: session.provider });
      if (row && (row.title.toLowerCase().includes(fold) || row.project.toLowerCase().includes(fold))) named.push(row);
    }
    for (const team of teams ?? []) {
      const projectId = projectIdFor({ session_id: team.team_id, cwd: team.cwd }, projects, projectOf);
      if (!projectId) continue;
      const project = projectName.get(projectId) ?? "";
      const title = team.title || t("team_threads.new");
      if (!title.toLowerCase().includes(fold) && !project.toLowerCase().includes(fold)) continue;
      named.push({ key: `team:${team.team_id}`, kind: "team", id: team.team_id, projectId, title, project,
        updated: team.updated_ms, provider: "", snippet: "", matches: 0 });
    }
    named.sort((a, b) => b.updated - a.updated).forEach(add);
    // Then what the messages say; a title hit also gains the line that matched.
    const found = hits && hits.query === needle ? hits.rows : [];
    for (const hit of found) {
      const existing = out.get(`thread:${hit.session_id}`);
      if (existing) { if (hit.snippet) Object.assign(existing, { snippet: hit.snippet, matches: hit.matches }); continue; }
      const row = threadRow(hit.session_id, hit.cwd, { title: hit.title, updated: hit.updated_ms, provider: "" },
        { snippet: hit.snippet, matches: hit.matches });
      if (row) add(row);
    }
    return [...out.values()];
  }, [needle, sessions, teams, hits, projects, projectOf, t]);

  // The first row stays selected as results arrive.
  const firstKey = rows[0]?.key ?? "";
  useEffect(() => { setSelected(firstKey); }, [firstKey]);

  const searching = Boolean(needle) && (!hits || hits.query !== needle);

  const choose = (row: Row) => {
    if (row.kind === "team") openTeam(row.id, row.projectId);
    else openThread(row.id, row.projectId);
    onOpened?.(row.projectId);
    onClose();
  };

  return <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-[80]" />
      <Dialog.Content
        data-testid="thread-search"
        aria-describedby={undefined}
        className={cn(
          "fixed left-1/2 top-[16%] z-[90] w-[min(620px,calc(100vw-2rem))] -translate-x-1/2",
          "overflow-hidden rounded-xl border border-border shadow-float",
          "backdrop-blur-2xl backdrop-saturate-150",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 motion-reduce:animate-none",
        )}
        style={{ backgroundColor: "hsl(var(--popover) / 0.92)" }}
      >
        <Dialog.Title className="sr-only">{t("ide_threads.search_threads")}</Dialog.Title>
        <Command shouldFilter={false} loop label={t("ide_threads.search_threads")} value={selected} onValueChange={setSelected}>
          <div className="flex items-center gap-2.5 border-b border-border px-4">
            <SearchThreadsIcon className="h-[18px] w-[18px] shrink-0 text-muted-foreground" />
            <Command.Input autoFocus value={query} onValueChange={setQuery}
              placeholder={t("ide_threads.search_placeholder")} data-testid="thread-search-input"
              className="h-12 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground" />
            {searching && <Loader2 aria-label={t("ide_threads.search_searching")} className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />}
          </div>
          <Command.List className="max-h-[min(28rem,60dvh)] overflow-y-auto p-1.5">
            {rows.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              {needle ? (searching ? t("ide_threads.search_searching") : t("ide_threads.search_none")) : t("ide_threads.search_empty")}
            </div>}
            {rows.length > 0 && <Command.Group
              heading={needle ? t("ide_threads.search_results") : t("ide_threads.search_recent")}
              className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground">
              {rows.map((row) => {
                const mark = row.kind === "thread" ? agentOf.get(row.provider) : undefined;
                return <Command.Item key={row.key} value={row.key} onSelect={() => choose(row)}
                  data-testid={`thread-search-row-${row.id}`}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 text-left data-[selected=true]:bg-secondary">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                    {row.kind === "team"
                      ? <TeamThreadIcon className="h-4 w-4" />
                      : mark ? <AgentMark agent={mark.agent} label={mark.label} variant="plain" size="sm" /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm text-foreground"><Marked text={row.title} needle={needle} /></span>
                      <span className="shrink-0 truncate text-xs text-muted-foreground">{row.project}</span>
                      <span className="w-7 shrink-0 text-right text-micro tabular-nums text-muted-foreground">{shortAge(row.updated)}</span>
                    </span>
                    {row.snippet && <span className="mt-0.5 flex min-w-0 items-baseline gap-2 text-xs text-muted-foreground">
                      <span className="min-w-0 flex-1 truncate"><Marked text={row.snippet} needle={needle} /></span>
                      {row.matches > 1 && <span className="shrink-0 tabular-nums">{fill(t("ide_threads.search_matches"), { count: row.matches })}</span>}
                    </span>}
                  </span>
                </Command.Item>;
              })}
            </Command.Group>}
          </Command.List>
        </Command>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
