import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Loader2, Search, TriangleAlert, type LucideIcon } from "lucide-react";

import { ArtifactsIcon, CaptureIcon, ChatIcon, ExtensionsIcon, SpeechIcon } from "@/components/icons/sectionIcons";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useArtifactFavorites } from "@/hooks/useArtifactFavorites";
import { fetchOutputsList, type ArtifactsResponse, type OutputSummary } from "@/hooks/useOutputs";
import { toVisuals, visualId, type VisualArtifact } from "@/hooks/useVisualArtifacts";
import { useT } from "@/i18n";
import { identityAvatarStyle } from "@/lib/identityAvatar";
import { cn } from "@/lib/utils";
import { useEventStore, type SectionId } from "@/store/events";
import { useQuickSwitcher } from "@/store/quickSwitcher";

import { useStatusLightStore, watchStatusLight, type StatusLightData } from "./statusLightStore";
import {
  StatusGroup, StatusTroubleGroup, TILE_TONE, goToStatusRow, openKeys, statusKindIcon, troubleItems, type StatusTone,
} from "./statusRows";

/** The conversation and the pages reached most from beside it, in the maintainer's order. */
const SHORTCUTS: readonly { id: SectionId; labelKey: string; Icon: LucideIcon; also: readonly SectionId[] }[] = [
  { id: "chats", labelKey: "sidebar.surface_chat", Icon: ChatIcon, also: [] },
  { id: "plugins", labelKey: "nav.plugins", Icon: ExtensionsIcon, also: ["skills", "mcps"] },
  { id: "dictation", labelKey: "nav.dictation", Icon: SpeechIcon, also: ["dictionary", "voice-language", "voice-api-keys"] },
  { id: "visualization", labelKey: "nav.visualization", Icon: ArtifactsIcon, also: [] },
  { id: "appshots", labelKey: "nav.appshots", Icon: CaptureIcon, also: [] },
];

/** How many live tiles the rail shows before the rest moves behind a count. */
const EVENTS_SHOWN = 5;
/** How many artifacts the rail keeps one click away: the starred ones first, then the newest. */
const ARTIFACTS_SHOWN = 4;
/** How many of the newest runs are looked at to fill the places the stars leave. */
const RECENT_RUNS_READ = 5;
/** A finished page does not change by itself; its listing is read rarely. */
const LISTING_STALE_MS = 5 * 60_000;
/** A new run shows up on the rail within this time, without a poll worth noticing. */
const RUNS_STALE_MS = 2 * 60_000;

/** One round button of the rail: the shape every icon on it shares. */
export const RAIL_BUTTON =
  "relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
export const RAIL_BUTTON_ON = "bg-secondary text-foreground-strong";
export const RAIL_GLYPH = "h-6 w-6 shrink-0";
/** A smaller round tile: something live or something kept, not a place. */
const RAIL_TILE = "relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full ring-1 ring-inset transition-[filter,box-shadow] " +
  "hover:brightness-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Divider() {
  return <span aria-hidden className="my-1.5 h-px w-6 shrink-0 bg-border" />;
}

/** A rail icon says its name in a bubble to the right, never in a native tooltip. */
function Named({ name, children }: { name: string; children: ReactNode }) {
  return <QuickTooltip content={name} side="right" className="flex">{children}</QuickTooltip>;
}

/** One live thing as the rail draws it: a tinted round tile that leads to its place. */
interface RailEvent {
  key: string;
  tone: StatusTone;
  Icon: LucideIcon;
  spin: boolean;
  title: string;
  subtitle: string;
  kind: string;
  go?: () => void;
}

/** What waits on the person first, then what is in trouble, then what runs. */
function railEvents(light: StatusLightData | null, t: (key: string) => string): RailEvent[] {
  if (!light) return [];
  const needs = light.needs_you.map((row): RailEvent => ({
    key: `needs:${row.kind}:${row.id}`, tone: "needs", Icon: statusKindIcon(row.kind), spin: false, kind: row.kind,
    title: row.title, subtitle: t(`status_light.kind_${row.kind}`), go: () => goToStatusRow(row),
  }));
  const trouble = troubleItems(light.trouble, light.findings, t).map((item): RailEvent => ({
    key: `trouble:${item.key}`, tone: "trouble", Icon: TriangleAlert, spin: false, kind: item.kind,
    title: item.title, subtitle: item.subtitle, go: item.opensKeys ? () => openKeys() : undefined,
  }));
  const running = light.running.map((row): RailEvent => ({
    key: `running:${row.kind}:${row.id}`, tone: "running", Icon: Loader2, spin: true, kind: row.kind,
    title: row.title, subtitle: t(`status_light.kind_${row.kind}`), go: () => goToStatusRow(row),
  }));
  return [...needs, ...trouble, ...running];
}

/** A dot in the tile's corner for what waits on the person: the one tone that asks for a click. */
function NeedsDot() {
  return <span aria-hidden className="absolute right-0 top-0 h-2.5 w-2.5 rounded-full bg-primary ring-2 ring-sidebar" />;
}

function EventTile({ event }: { event: RailEvent }) {
  const name = `${event.title}\n${event.subtitle.charAt(0).toUpperCase()}${event.subtitle.slice(1)}`;
  const glyph = <event.Icon aria-hidden strokeWidth={1.75} className={cn("h-5 w-5", event.spin && "motion-safe:animate-spin")} />;
  const shape = cn(RAIL_TILE, TILE_TONE[event.tone]);
  return (
    <Named name={name}>
      <span className="relative flex">
        {event.go
          ? <button type="button" onClick={event.go} aria-label={`${event.title} · ${event.subtitle}`}
            data-testid="rail-event" data-tone={event.tone} data-kind={event.kind} className={shape}>{glyph}</button>
          : <span role="img" aria-label={`${event.title} · ${event.subtitle}`}
            data-testid="rail-event" data-tone={event.tone} data-kind={event.kind} className={shape}>{glyph}</span>}
        {event.tone === "needs" && <NeedsDot />}
      </span>
    </Named>
  );
}

/**
 * Everything that is going on, as the full list: opened from the count tile
 * when the rail holds more than it shows. It stands beside the rail and closes
 * on a click elsewhere, on Escape, or once a row took the person somewhere.
 */
function EventsPanel({ anchor, light, onClose }: { anchor: HTMLElement; light: StatusLightData; onClose: () => void }) {
  const t = useT();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    const height = panelRef.current?.getBoundingClientRect().height ?? 0;
    setPlace({ left: rect.right + 12, top: Math.max(8, Math.min(rect.top, window.innerHeight - height - 8)) });
  }, [anchor, light]);

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || anchor.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchor, onClose]);

  const go = (row: Parameters<typeof goToStatusRow>[0]) => { goToStatusRow(row); onClose(); };
  return createPortal(
    <div ref={panelRef} role="dialog" aria-label={t("status_light.title")} data-testid="rail-events-panel"
      style={{ left: place?.left ?? 0, top: place?.top ?? 0, visibility: place ? "visible" : "hidden" }}
      className="fixed z-[60] max-h-[calc(100vh-16px)] w-80 overflow-y-auto rounded-xl border border-border-strong bg-popover p-2 shadow-float scrollbar-jarvis">
      <StatusGroup title={t("status_light.needs_heading")} rows={light.needs_you} onGo={go} testId="rail-events-needs" />
      <StatusTroubleGroup trouble={light.trouble} findings={light.findings} testId="rail-events-trouble" onNavigate={onClose} />
      <StatusGroup title={t("status_light.running_heading")} rows={light.running} running onGo={go} testId="rail-events-running" />
    </div>,
    document.body,
  );
}

/**
 * What is live, as round tiles under the shortcuts: a question or an approval
 * that waits on the person, a provider in trouble, an agent at work. Each tile
 * says what it is on hover and leads to its place on a click. Nothing shows
 * while all is quiet.
 */
function RailEvents() {
  const t = useT();
  const light = useStatusLightStore((s) => s.light);
  useEffect(() => watchStatusLight(), []);
  const events = railEvents(light, t);
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  if (!light || events.length === 0) return null;

  // The count tile takes one of the places, so the rail never grows past its limit.
  const shown = events.length > EVENTS_SHOWN ? events.slice(0, EVENTS_SHOWN - 1) : events;
  const more = events.length - shown.length;
  const moreLabel = t("sidebar.rail_more_events").replace("{count}", String(more));
  return (
    <section aria-label={t("status_light.title")} data-testid="rail-events" className="flex flex-col items-center gap-1.5">
      <Divider />
      {shown.map((event) => <EventTile key={event.key} event={event} />)}
      {more > 0 && (
        <Named name={moreLabel}>
          <button ref={moreRef} type="button" data-testid="rail-events-more" aria-label={moreLabel} aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={cn(RAIL_TILE, "bg-secondary text-xs font-medium tabular-nums text-muted-foreground ring-border")}>
            +{more}
          </button>
        </Named>
      )}
      {open && moreRef.current && <EventsPanel anchor={moreRef.current} light={light} onClose={() => setOpen(false)} />}
    </section>
  );
}

/** The newest stars on artifacts (`<slug>::<path>`), newest first. A starred run without a page is not a tile. */
function starredKeys(favorites: ReadonlySet<string>): { slug: string; path: string }[] {
  const stars: { slug: string; path: string }[] = [];
  for (const key of favorites) {
    const cut = key.indexOf("::");
    if (cut <= 0 || key.startsWith("run:")) continue;
    stars.push({ slug: key.slice(0, cut), path: key.slice(cut + 2) });
  }
  return stars.slice(-ARTIFACTS_SHOWN).reverse();
}

/** What a run is known by on the rail: its page, else its newest picture or document. */
function leadVisual(visuals: VisualArtifact[]): VisualArtifact | null {
  if (visuals.length === 0) return null;
  const pages = visuals.filter((visual) => visual.kind === "page");
  return [...(pages.length > 0 ? pages : visuals)].sort((a, b) => b.mtime - a.mtime)[0];
}

/** Two letters for a title: the first letter of each of its first two words. */
export function tileInitials(title: string): string {
  const words = title.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (words.length === 0) return "?";
  return (words[0].charAt(0) + (words[1]?.charAt(0) ?? "")).toUpperCase();
}

function ArtifactTile({ visual, onOpen }: { visual: VisualArtifact; onOpen: () => void }) {
  const picture = visual.kind === "image" || visual.kind === "vector";
  return (
    <Named name={visual.title}>
      <button type="button" onClick={onOpen} aria-label={visual.title} data-testid="rail-artifact" data-kind={visual.kind}
        // A page has no face of its own, so it wears its title: two letters on the title's own hue.
        style={picture ? undefined : identityAvatarStyle(visual.title)}
        className={cn(RAIL_TILE, "text-sm font-semibold ring-transparent", picture && "bg-secondary ring-border")}>
        {picture
          ? <img src={visual.url} alt="" loading="lazy" draggable={false} className="h-full w-full object-cover" />
          : <span aria-hidden>{tileInitials(visual.title)}</span>}
      </button>
    </Named>
  );
}

/**
 * Artifacts one click away: the ones the person starred, then the newest the
 * assistant made. A picture shows itself, a page or a document two letters of
 * its title, each with the whole title on hover. A star on something that no
 * longer exists draws nothing.
 */
function RailArtifacts() {
  const t = useT();
  const { favorites } = useArtifactFavorites();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const stars = useMemo(() => starredKeys(favorites), [favorites]);
  // The key the Artifacts page reads under, so both share one answer. No fast
  // poll here: the rail is on screen all day and only has to notice a new run.
  const runs = useQuery<OutputSummary[]>({
    queryKey: ["outputs"], queryFn: fetchOutputsList, staleTime: RUNS_STALE_MS, refetchInterval: RUNS_STALE_MS,
    enabled: stars.length < ARTIFACTS_SHOWN,
  });
  const recent = useMemo(
    () => (runs.data ?? []).filter((run) => run.status !== "running").slice(0, RECENT_RUNS_READ).map((run) => run.slug),
    [runs.data],
  );
  const slugs = useMemo(() => [...new Set([...stars.map((star) => star.slug), ...recent])], [stars, recent]);
  const listings = useQueries({
    queries: slugs.map((slug) => ({
      queryKey: ["output-artifacts", slug],
      queryFn: async (): Promise<ArtifactsResponse> => {
        const response = await fetch(`/api/outputs/${encodeURIComponent(slug)}/artifacts`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      },
      staleTime: LISTING_STALE_MS,
      retry: false,
    })),
  });
  const visualsOf = (slug: string): VisualArtifact[] => {
    const files = listings[slugs.indexOf(slug)]?.data?.files;
    if (!files) return [];
    const run = runs.data?.find((candidate) => candidate.slug === slug) ?? ({ slug } as OutputSummary);
    return toVisuals(run, files);
  };
  const shown: VisualArtifact[] = [];
  for (const star of stars) {
    const visual = visualsOf(star.slug).find((candidate) => candidate.path === star.path);
    if (visual) shown.push(visual);
  }
  for (const slug of recent) {
    if (shown.length >= ARTIFACTS_SHOWN) break;
    const visual = leadVisual(visualsOf(slug));
    if (visual && !shown.some((taken) => taken.slug === visual.slug)) shown.push(visual);
  }
  if (shown.length === 0) return null;
  return (
    <section aria-label={t("sidebar.rail_artifacts")} data-testid="rail-artifacts" className="flex flex-col items-center gap-1.5">
      <Divider />
      {shown.map((visual) => (
        <ArtifactTile key={visualId(visual)} visual={visual} onOpen={() => requestVisual(visualId(visual))} />
      ))}
    </section>
  );
}

/**
 * The column beside the conversation: a rail of round icons. On top the
 * conversation, search and the pages reached most; under them what is live
 * right now, and the artifacts the person starred or the assistant made last.
 * Every icon says its name on hover, so the rail needs no words of its own.
 */
export function NavRail({ searchOn, pluginsWarn }: {
  /** The quick switcher is on, so search has a place on the rail. */
  searchOn: boolean;
  /** Why the Plugins icon carries a dot, or null when it carries none. */
  pluginsWarn: string | null;
}) {
  const t = useT();
  const active = useEventStore((s) => s.activeSection);
  const setActive = useEventStore((s) => s.setActiveSection);
  const searchLabel = t("quick_switch.sidebar_search");

  return (
    <div data-testid="nav-rail" className="flex flex-col items-center gap-1.5 pb-3 pt-1">
      <nav aria-label={t("sidebar.sections")} data-testid="sidebar-shortcuts">
        <ul className="m-0 flex list-none flex-col items-center gap-1.5 p-0">
          {SHORTCUTS.map((item, index) => {
            const { id, labelKey, Icon, also } = item;
            const here = active === id || also.includes(active);
            const warn = id === "plugins" ? pluginsWarn : null;
            const label = t(labelKey);
            return [
              <li key={id}>
                <Named name={warn ? `${label}\n${warn}` : label}>
                  <button type="button" data-testid={`sidebar-shortcut-${id}`} data-tour={`nav-${item.id}`} onClick={() => setActive(id)}
                    aria-label={label} aria-current={here ? "page" : undefined}
                    className={cn(RAIL_BUTTON, here && RAIL_BUTTON_ON)}>
                    <Icon aria-hidden strokeWidth={1.6} className={RAIL_GLYPH} />
                    {warn && <span data-testid="sidebar-shortcut-warn" role="status" aria-label={warn}
                      className="absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-warning ring-2 ring-sidebar" />}
                  </button>
                </Named>
              </li>,
              // Search stands second, right under the conversation.
              index === 0 && searchOn && (
                <li key="search">
                  <Named name={searchLabel}>
                    <button type="button" data-testid="sidebar-search-row" aria-label={searchLabel}
                      onClick={() => useQuickSwitcher.getState().show()} className={RAIL_BUTTON}>
                      <Search aria-hidden strokeWidth={1.6} className={RAIL_GLYPH} />
                    </button>
                  </Named>
                </li>
              ),
            ];
          })}
        </ul>
      </nav>
      <RailEvents />
      <RailArtifacts />
    </div>
  );
}
