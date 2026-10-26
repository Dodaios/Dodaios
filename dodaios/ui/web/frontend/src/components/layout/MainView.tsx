import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type LazyExoticComponent,
  type ReactNode,
} from "react";
import { Loader2 } from "lucide-react";
import { useEventStore, type SectionId } from "@/store/events";
import { sectionPrefetch } from "@/lib/sectionPrefetch";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ViewErrorBoundary } from "@/components/ViewErrorBoundary";
import { SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { sectionWindow } from "@/lib/sectionWindows";
import { FULL_RECT, layoutLeaves, type TileRect } from "@/lib/tilingLayout";
import { useTilingStore } from "@/store/tiling";
import { useWallpaper } from "@/hooks/useWallpaper";
import { TileHeader, TILE_DRAG_TYPE } from "@/components/layout/tiling/TileHeader";
import { TileGutters } from "@/components/layout/tiling/TileGutters";
import { TileSectionContext } from "@/components/layout/tiling/tileSection";
// Type-only, so the section's chunk stays split out of the entry bundle.
import type { AgenticIdeViewProps } from "@/views/AgenticIdeView";
// The default section is the one view that must be on screen the moment React
// mounts, so it stays statically linked into the entry chunk. Every other view
// is code-split below. `ChatsSurface` picks the mission deck or the classic
// chat view from the stored preference — both travel in the entry chunk because
// either one can be the very first thing painted.
import { ChatsSurface } from "@/views/ChatsSurface";

/**
 * Keep unused views out of every window's startup work. Navigation loads its
 * view through React.lazy; a deliberate sidebar hover/focus warms only that
 * destination. Blanket idle imports used to execute all 14 views per window.
 */
type ViewModule = { default: ComponentType };
type ViewLoader = () => Promise<ViewModule>;

function lazyView(
  sections: readonly SectionId[],
  loader: ViewLoader,
): LazyExoticComponent<ComponentType> {
  sectionPrefetch.register(sections, loader);
  return lazy(loader);
}

/**
 * The same, for the one view the shell has to tell something.
 *
 * Sections are otherwise self-contained and take no props — a section knows
 * which one it is and reads the rest from the store. The Agentic IDE is the
 * exception because it is the one section that stays mounted while hidden, and
 * "are you the section on screen right now?" is a question only the shell can
 * answer for it (see `MainView`).
 */
function lazyPropView<P>(
  sections: readonly SectionId[],
  loader: () => Promise<{ default: ComponentType<P> }>,
): LazyExoticComponent<ComponentType<P>> {
  sectionPrefetch.register(sections, loader);
  return lazy(loader);
}

// Views are named exports, hence the explicit React.lazy default unwrap.
// The Settings hub — Profile, {name}.md, Contacts, Socials, API Keys, Local
// models, Spend and Feedback behind one left-nav dialog. The hub
// statically owns only its shell; every tab stays its own lazy chunk (see
// SettingsHubView), so this one import replaces the eleven per-view imports
// below without merging their chunks back together.
const SettingsHubDialog = lazyPropView<{ onClose: () => void }>(SETTINGS_HUB_IDS, () =>
  import("@/views/SettingsHubView").then((m) => ({ default: m.SettingsHubDialog })),
);
const SettingsHubView = lazy(() =>
  import("@/views/SettingsHubView").then((m) => ({ default: m.SettingsHubView })),
);
// The Agents section is the society (MASTERPLAN §4.1): stage + agents rail +
// model cards. The board it replaced is the society's stage until the island
// lands, loaded by SocietyView itself.
const SocietyView = lazyView(["agents"], () =>
  import("@/views/society/SocietyView").then((m) => ({
    default: m.SocietyView,
  })),
);
const MemoryView = lazyView(["memory"], () =>
  import("@/views/MemoryView").then((m) => ({ default: m.MemoryView })),
);
type PluginArea = "plugins" | "mcps" | "skills";
const isPluginArea = (section: string): section is PluginArea =>
  section === "plugins" || section === "mcps" || section === "skills";
const isSettingsHub = (section: string) =>
  (SETTINGS_HUB_IDS as readonly string[]).includes(section);
// Sections that float as a dialog over the last regular section instead of
// replacing it.
const isOverlaySection = (section: string) => isPluginArea(section) || isSettingsHub(section);

const PluginsDialog = lazyPropView<{ onClose: () => void; area: PluginArea; standalone?: boolean; onAreaChange: (area: PluginArea) => void }>(["plugins", "mcps", "skills"], () =>
  import("@/views/PluginsDialog").then((m) => ({ default: m.PluginsDialog })),
);
// The prop type is named rather than inferred: inferring it from the loader's
// return value is circular (the loader's contextual type is what depends on it),
// and TypeScript resolves that by falling back to `never`.
const AgenticIdeView = lazyPropView<AgenticIdeViewProps>(["agentic-ide", "agentic-ide-classic", "chat-workspace"], () =>
  import("@/views/AgenticIdeView").then((m) => ({ default: m.AgenticIdeView })),
);
const SessionsView = lazyView(["sessions"], () =>
  import("@/views/SessionsView").then((m) => ({ default: m.SessionsView })),
);
const ClisHubView = lazyView(["clis", "cli-test-hub"], () =>
  import("@/views/ClisHubView").then((m) => ({ default: m.ClisHubView })),
);
const DocsView = lazyView(["docs"], () =>
  import("@/views/DocsView").then((m) => ({ default: m.DocsView })),
);
const BoardView = lazyView(["board"], () =>
  import("@/views/BoardView").then((m) => ({ default: m.BoardView })),
);
// Dictation + Dictionary + Shortcuts + Language + Voice API keys are merged
// behind the one "{name} Voice" sidebar entry. Only the hub is split out here —
// it statically imports its five tabs, so they travel in its chunk instead of
// being prefetched as separate ones.
const VoiceHubView = lazyView(["dictation", "dictionary", "voice-shortcuts", "voice-language", "voice-api-keys"], () =>
  import("@/views/VoiceHubView").then((m) => ({ default: m.VoiceHubView })),
);
const VisualizationView = lazyView(["visualization"], () =>
  import("@/views/VisualizationView").then((m) => ({
    default: m.VisualizationView,
  })),
);
const MarketplaceView = lazyView(["marketplace"], () =>
  import("@/views/MarketplaceView").then((m) => ({
    default: m.MarketplaceView,
  })),
);
const SelfBuildView = lazyView(["self-build"], () =>
  import("@/views/SelfBuildView").then((m) => ({
    default: m.SelfBuildView,
  })),
);

/** Quiet time before a loading section admits it is loading. */
export const LOADING_HINT_MS = 400;

/** After this, the wait stops being normal and the placeholder says so. */
export const LOADING_SLOW_MS = 8_000;

/**
 * Placeholder shown while a section chunk is in flight.
 *
 * It used to render nothing at all, on the reasoning that the idle prefetch
 * makes this almost invisible and a spinner shown for 30 ms reads as a
 * flicker. The first half of that holds; the second half assumed the wait is
 * always ~30 ms, and it is not. Every asset is served from the one asyncio
 * loop the whole backend shares, so any synchronous call on that loop stops
 * the chunk mid-flight — measured on the maintainer's box at 15.0 s, 15.1 s,
 * 15.2 s, 16.2 s and 17.9 s. For all of that time the only thing painted here
 * is the section stage's own ground, `rgb(10, 10, 10)`: an unannounced black
 * rectangle where the app used to be. That is what gets reported as "the app
 * goes black when I switch sections", and it is a missing loading state rather
 * than a crash.
 *
 * So the quiet is kept where it was earned and dropped where it was not:
 * nothing for {@link LOADING_HINT_MS}, so a warm chunk still swaps in without
 * a flash; a calm spinner once the wait is long enough to notice; and past
 * {@link LOADING_SLOW_MS} a line saying it is taking longer than usual, so a
 * stalled backend looks like a slow app instead of a dead one.
 */
export function ViewLoadingFallback() {
  const t = useT();
  const [phase, setPhase] = useState<"quiet" | "loading" | "slow">("quiet");

  useEffect(() => {
    const hint = window.setTimeout(() => setPhase("loading"), LOADING_HINT_MS);
    const slow = window.setTimeout(() => setPhase("slow"), LOADING_SLOW_MS);
    return () => {
      window.clearTimeout(hint);
      window.clearTimeout(slow);
    };
  }, []);

  return (
    <div
      className="flex h-full w-full flex-col items-center justify-center gap-3 bg-background"
      aria-busy="true"
      role="status"
      data-testid="view-loading-fallback"
      data-phase={phase}
    >
      {phase !== "quiet" && (
        <>
          {/* Secondary ink, not the accent: `--primary` is a fill — buttons,
              marks, focus rings — and an icon painted in it outshines every
              heading on the screen behind it. */}
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <p className="text-body text-muted-foreground">{t("view_loading.loading")}</p>
          {phase === "slow" && (
            <p className="max-w-[46ch] text-center text-meta text-muted-foreground">
              {t("view_loading.slow")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/**
 * The section ids that all mean "the coding workspace".
 *
 * There is ONE coding surface again: the terminal workspace. A separate chat
 * surface was tried in front of it and taken back out — it rendered a picture of
 * the agent while the agent itself ran behind it, which is one thing too many
 * for a screen whose whole job is showing what the agent is doing. The extra
 * ids stay valid because deep links, voice commands and stored preferences
 * already point at them, and an id that stops resolving is a dead end for
 * somebody who never chose either name.
 */
const CODING_SECTION_IDS = ["agentic-ide", "agentic-ide-classic", "chat-workspace"] as const;

/**
 * The one section that is hidden rather than unmounted — see `MainView`.
 *
 * What makes a section too destructive to unmount is LIVE PANES, and this is
 * where those live.
 */
const STICKY_SECTION = "agentic-ide";

/*
 * No shell-level page measure. One was tried on 2026-09-01 (a centred 1080 px
 * column around every section except the coding workspace): on a 4K window it
 * squeezed the wiki graph into a thumbnail, tore the sub-navigation columns
 * off the left edge, and centred single-column forms in a sea of black. The
 * maintainer's verdict was "you broke many sections". Every view keeps
 * deciding its own width; a view that needs a measure applies `max-w-reading`
 * / `max-w-form` / `max-w-page` to the element that actually needs it.
 */

/** Space between tiles, and between the tiles and the stage edge, in px. */
const TILE_GAP = 14;

/** Where one section sits on the stage; `rect` null = mounted but hidden. */
interface Placement {
  section: SectionId;
  leafId: string | null;
  rect: TileRect | null;
  focused: boolean;
}

const isCoding = (section: string) => (CODING_SECTION_IDS as readonly string[]).includes(section);

/**
 * Main area to the right of the sidebar.
 *
 * Two shapes. Classic: one section fills the stage. Tiled: several sections
 * share it side by side over the wallpaper, in the layout the tiling store
 * holds (see `store/tiling.ts`). Both shapes render the same flat, keyed list
 * of frames, so a section that moves between them — or from one tile to
 * another — keeps its state instead of mounting again.
 *
 * Views are otherwise switched the classic way (one view per frame, the
 * others unmounted) — this saves render load and is semantically fine because
 * they rehydrate their state from React Query / the store.
 *
 * The Agentic IDE is the ONE exception, and it is not an optimisation: its
 * panes are live terminals, and unmounting them is destructive in a way no
 * other section's state is. Leaving the section tore down a dozen xterm
 * instances and their sockets, and coming back rebuilt every one of them —
 * each re-attach replays up to `REPLAY_LIMIT_CHARS` of raw output per pane, so
 * a workspace of eleven terminals pushed well over a megabyte through the main
 * thread just to show what was already on screen three seconds earlier. Worse,
 * the remounted view starts out knowing of no workspace at all, so the first
 * thing the user saw on the way back was the onboarding wizard asking which
 * folder to open — in front of a workspace that had never stopped running
 * (maintainer report 2026-07-29).
 *
 * So once opened, it stays mounted and is hidden with CSS instead. That costs
 * nothing while it is away: the panes' `IntersectionObserver` already treats
 * `display: none` as off-screen and parks their output (see AgenticTerminal),
 * and their `ResizeObserver` re-fits them when they come back. Sticky rather
 * than always-mounted so a user who never opens the section never pays for it.
 * It is mounted at most ONCE: a second instance would steal every pane's
 * output stream from the first, which is why a section family sits in one
 * tile only.
 */
export function MainView() {
  const active = useEventStore((s) => s.activeSection);
  const setActive = useEventStore((s) => s.setActiveSection);
  const solo = useEventStore((s) => s.solo);
  const tree = useTilingStore((s) => s.tree);
  const focusedId = useTilingStore((s) => s.focusedId);
  const maximizedId = useTilingStore((s) => s.maximizedId);
  const tiled = tree !== null && !solo;
  const [backgroundSection, setBackgroundSection] = useState(
    isOverlaySection(active) ? "chats" : active,
  );
  if (!isOverlaySection(active) && backgroundSection !== active) setBackgroundSection(active);
  const displayed = isOverlaySection(active) ? backgroundSection : active;
  const soloOverlay = solo && isOverlaySection(active);

  const placements: Placement[] = soloOverlay
    ? []
    : tree && tiled
      ? layoutLeaves(tree).map(({ leaf, rect }) => ({
          section: leaf.section,
          leafId: leaf.id,
          rect: maximizedId ? (leaf.id === maximizedId ? FULL_RECT : null) : rect,
          focused: leaf.id === focusedId,
        }))
      : [{ section: displayed, leafId: null, rect: FULL_RECT, focused: true }];

  const idePlacement = placements.find((item) => isCoding(item.section));
  const stickyActive = !!idePlacement?.rect;
  const [stickyMounted, setStickyMounted] = useState(stickyActive);
  useEffect(() => {
    if (stickyActive) setStickyMounted(true);
  }, [stickyActive]);

  const wallpaper = useWallpaper(tiled);
  const stage = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = stage.current;
    if (!tiled || !node || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const { width, height } = node.getBoundingClientRect();
      if (width > 0 && height > 0) useTilingStore.getState().setStageAspect(width / height);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [tiled]);

  return (
    <div
      ref={stage}
      className={cn("relative h-full w-full", tiled && "jarvis-tiling-stage")}
      style={tiled && wallpaper ? { backgroundImage: `url("${wallpaper}")` } : undefined}
      data-testid={tiled ? "tiling-stage" : undefined}
    >
      <div className="absolute inset-0" style={tiled ? { padding: TILE_GAP / 2 } : undefined}>
        <div className="relative h-full w-full">
          {stickyMounted && !soloOverlay && (
            <TileFrame
              placement={idePlacement ?? { section: STICKY_SECTION, leafId: null, rect: null, focused: false }}
              tiled={tiled}
              maximized={!!idePlacement?.leafId && idePlacement.leafId === maximizedId}
              testId="sticky-agentic-ide"
            >
              {/* Its own boundary, un-keyed: this instance must survive every
                  section change, which is the entire point of keeping it. */}
              <ViewErrorBoundary
                viewName={STICKY_SECTION}
                resetKey={STICKY_SECTION}
                onRecover={() => setActive("chats")}
              >
                <Suspense fallback={<ViewLoadingFallback />}>
                  {/* Told rather than measured: a `display: none` subtree has no
                      geometry to read, and the view's background polling has to
                      know it is off screen so it can stop asking the backend what
                      a dozen panes are doing while nobody is watching them. */}
                  <AgenticIdeView onScreen={stickyActive} />
                </Suspense>
              </ViewErrorBoundary>
            </TileFrame>
          )}
          {placements
            .filter((item) => !isCoding(item.section))
            .map((item) => (
              <TileFrame
                key={sectionWindow(item.section)}
                placement={item}
                tiled={tiled}
                maximized={!!item.leafId && item.leafId === maximizedId}
              >
                <ViewErrorBoundary
                  viewName={item.section}
                  resetKey={item.section}
                  onRecover={() => setActive("chats")}
                >
                  {/* Keyed on the section so switching away from a still-loading
                      view cannot leave the previous section's fallback on screen. */}
                  <Suspense key={item.section} fallback={<ViewLoadingFallback />}>
                    <SwitchOnActiveSection active={item.section} />
                  </Suspense>
                </ViewErrorBoundary>
              </TileFrame>
            ))}
          {tree && tiled && !maximizedId && <TileGutters tree={tree} gap={TILE_GAP} />}
        </div>
      </div>
      {isPluginArea(active) && (
        <ViewErrorBoundary viewName="plugins" resetKey="plugins" onRecover={() => setActive(backgroundSection)}>
          <Suspense fallback={null}>
            <PluginsDialog standalone={solo} area={active} onAreaChange={setActive} onClose={() => setActive(backgroundSection)} />
          </Suspense>
        </ViewErrorBoundary>
      )}
      {isSettingsHub(active) && (
        <ViewErrorBoundary viewName="settings" resetKey="settings" onRecover={() => setActive(backgroundSection)}>
          <Suspense fallback={null}>
            {solo ? <SettingsHubView /> : <SettingsHubDialog onClose={() => setActive(backgroundSection)} />}
          </Suspense>
        </ViewErrorBoundary>
      )}
    </div>
  );
}

/**
 * One section's frame on the stage.
 *
 * Classic shape: fills the stage, no chrome. Tiled: a rounded card at its
 * place in the layout with a slim title row; a press anywhere inside focuses
 * it, and another tile's title row dropped on it swaps the two.
 */
function TileFrame({
  placement,
  tiled,
  maximized,
  testId,
  children,
}: {
  placement: Placement;
  tiled: boolean;
  maximized: boolean;
  testId?: string;
  children: ReactNode;
}) {
  const { rect, leafId, focused, section } = placement;
  const [dropTarget, setDropTarget] = useState(false);
  const visible = rect !== null;
  const inner = (
    <TileSectionContext.Provider value={section}>{children}</TileSectionContext.Provider>
  );

  // One element shape for both cases — outer box, optional title row, content
  // box — so a section that moves between the classic stage and a tile keeps
  // its React subtree (and the IDE its live terminals).
  const tile = tiled && leafId !== null;
  const half = TILE_GAP / 2;
  const style: CSSProperties | undefined = tile && rect
    ? {
        left: `calc(${rect.x * 100}% + ${half}px)`,
        top: `calc(${rect.y * 100}% + ${half}px)`,
        width: `calc(${rect.w * 100}% - ${TILE_GAP}px)`,
        height: `calc(${rect.h * 100}% - ${TILE_GAP}px)`,
      }
    : undefined;

  return (
    <div
      className={cn(
        tile
          ? cn(
              "jarvis-tile absolute flex flex-col overflow-hidden rounded-xl border",
              focused ? "jarvis-tile-focused" : "border-white/10",
              dropTarget && "ring-2 ring-primary",
            )
          : "absolute inset-0 flex flex-col",
        !visible && "hidden",
      )}
      style={style}
      data-testid={testId ?? (tile ? "tile" : undefined)}
      data-focused={(tile && focused) || undefined}
      // Hidden from assistive technology too while it is off screen: the
      // panes stay in the DOM, and a screen reader walking a workspace's
      // worth of terminal output behind the visible section would be a
      // wall of noise nobody asked for.
      aria-hidden={!visible}
      onPointerDownCapture={tile && leafId ? () => {
        if (!focused) useTilingStore.getState().focusTile(leafId);
      } : undefined}
      onDragOver={tile ? (event) => {
        if (!event.dataTransfer.types.includes(TILE_DRAG_TYPE)) return;
        event.preventDefault();
        setDropTarget(true);
      } : undefined}
      onDragLeave={tile ? () => setDropTarget(false) : undefined}
      onDrop={tile && leafId ? (event) => {
        setDropTarget(false);
        const from = event.dataTransfer.getData(TILE_DRAG_TYPE);
        if (from && from !== leafId) {
          event.preventDefault();
          useTilingStore.getState().swapTiles(from, leafId);
        }
      } : undefined}
    >
      {tile && leafId && (
        <TileHeader leafId={leafId} section={section} focused={focused} maximized={maximized} />
      )}
      <div className={tile ? "jarvis-section-stage relative min-h-0 flex-1" : "relative min-h-0 flex-1"}>
        {inner}
      </div>
    </div>
  );
}

function SwitchOnActiveSection({ active }: { active: string }) {
  switch (active) {
    case "chats":
      return <ChatsSurface />;
    case "agents":
      return <SocietyView />;
    // CLIs list + CLI Test Hub are merged behind the "CLIs" entry.
    case "clis":
    case "cli-test-hub":
      return <ClisHubView />;
    case "docs":
      return <DocsView />;
    case "sessions":
      return <SessionsView />;
    case "board":
      return <BoardView />;
    case "memory":
      return <MemoryView />;
    // The merged voice section: Dictation (default landing) + Dictionary +
    // Shortcuts + Language + the speech-to-text keys, behind one tab bar. The
    // active id doubles as the tab state, so a voice deep-link to any of them
    // still lands on the right tab.
    case "dictation":
    case "dictionary":
    case "voice-shortcuts":
    case "voice-language":
    case "voice-api-keys":
      return <VoiceHubView />;
    // The visual stage for what a run produced. Rendered through the same
    // switch as every other section — the shell only decides what the stage
    // AROUND it looks like (see App.tsx).
    case "visualization":
      return <VisualizationView />;
    // The marketplace storefront: everything the community published, in one
    // place, installable without leaving the app.
    case "marketplace":
      return <MarketplaceView />;
    // Built for you: every self-built thing, with keep, undo and the pause.
    case "self-build":
      return <SelfBuildView />;
    // Deliberately nothing: the coding workspace is rendered by the STICKY
    // branch in `MainView` above, which keeps it mounted across section
    // changes. This switch is not rendered at all while one of those ids is
    // active, so reaching here would mean two live copies of a workspace's
    // terminals — the second of which would steal every pane's output stream
    // from the first.
    case "agentic-ide":
    case "agentic-ide-classic":
    case "chat-workspace":
      return null;
    default:
      return <ChatsSurface />;
  }
}
