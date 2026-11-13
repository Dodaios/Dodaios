/**
 * The Nodes library: everything the assistant made and keeps, on one page.
 *
 * Top to bottom: the section's name; a row with the tabs on the left and
 * three bare tools on the right (search, filter and order, grid or list);
 * the "Make something new" row of type tiles; and the cards. A card is the
 * node's cover with its name, its date and its state under it. The whole
 * card opens the node; a star and a "more" menu sit on the cover's corner.
 *
 * The page owns no data and no choices: both come in as `library`
 * (`useNodesLibrary`), so the section view can keep them alive while a node
 * is open. What the page does own is what is open ON it: the search field,
 * the filter panel, the card menu, and the dialog a type tile leads to.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Ellipsis, LayoutGrid, List, ListFilter, Loader2, Search, Shapes, Star, X } from "lucide-react";

import { useRunLocale } from "@/components/runs/format";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { QuickTooltip } from "@/components/ui/tooltip";
import type { OutputSummary } from "@/hooks/useOutputs";
import { useT } from "@/i18n";
import { endMissionDrag, startMissionDrag } from "@/lib/missionDnd";
import { cn } from "@/lib/utils";
import {
  LIBRARY_SORTS,
  LIBRARY_TABS,
  cardWhen,
  isPendingCard,
  showsNewRow,
  typeFilterApplies,
  type LibrarySort,
  type LibraryTab,
  type TypeFilter,
} from "./libraryModel";
import { NewNodeDialog } from "./NewNodeDialog";
import { NewNodeRow } from "./NewNodeRow";
import { NODE_MENU_WIDTH, cardIsWorking, useNodeCardActions, type NodeCardActions } from "./NodeCardMenu";
import { NodeCover } from "./NodeCover";
import { NODE_TYPES, type NodeCard, type NodeType } from "./nodeModel";
import { NODE_TYPE_LABEL_KEY } from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";
import type { NodesLibraryState } from "./useNodesLibrary";

type Translate = (key: string) => string;

/** How many skeleton cards stand in for a library that has not answered yet. */
const SKELETON_CARDS = 6;

const GRID_CLASS = "grid gap-7 grid-cols-[repeat(auto-fill,minmax(min(300px,100%),1fr))]";

/** A bare tool in the header row: no rim, a fill only under the pointer. */
const TOOL_BUTTON =
  "relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground " +
  "transition-colors duration-fast hover:bg-secondary hover:text-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "[&_svg]:h-[18px] [&_svg]:w-[18px]";

/** The small buttons on a cover's corner and at the end of a list row. */
const CARD_BUTTON =
  "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground " +
  "transition-[opacity,background-color,color,transform] duration-fast hover:text-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-safe:active:scale-95 " +
  "[&_svg]:h-4 [&_svg]:w-4";

/** Hidden until the card is under the pointer or holds the focus; always there on touch. */
const REVEALED_ON_CARD =
  "opacity-0 group-hover/card:opacity-100 group-focus-within/card:opacity-100 " +
  "[@media(hover:none)]:opacity-100 data-[open=true]:opacity-100";

export function NodesLibrary({
  library,
  onOpen,
}: {
  library: NodesLibraryState;
  onOpen: (card: NodeCard) => void;
}) {
  const t = useT();
  const [newType, setNewType] = useState<NodeType | null>(null);

  const open = useCallback(
    (card: NodeCard) => {
      // A placeholder is a promise, not a node: there is nothing to open yet.
      if (!isPendingCard(card)) onOpen(card);
    },
    [onOpen],
  );
  const actions = useNodeCardActions({
    favorites: library.favorites,
    onToggleFavorite: library.toggleFavorite,
    onOpen: open,
  });

  const { tab, search, typeFilter, view, loading, failed } = library;
  const shown = [...library.pending, ...library.cards];
  /** Nothing was ever made: no tabs to pick from, only the invitation. */
  const bare = !loading && !failed && library.allCards.length === 0 && library.pending.length === 0;
  const newRow = !failed && (bare || showsNewRow(tab, search, typeFilter));
  const skippedRuns = library.nodes.data?.skipped_runs ?? 0;
  const scannedRuns = library.nodes.data?.scanned_runs ?? 0;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="nodes-library">
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto w-full max-w-[1680px] px-6 pb-16 pt-10 md:px-10 xl:px-12">
          <h1
            className="font-display text-display tracking-tight text-foreground-strong"
            data-testid="nodes-title"
          >
            {t("nodes.title")}
          </h1>

          {!bare && (
            <div className="mt-5 flex min-h-8 flex-wrap items-center gap-x-4 gap-y-2">
              <LibraryTabs
                tab={tab}
                counts={library.counts}
                showCounts={!loading && !failed}
                onChange={library.setTab}
              />
              <div className="ml-auto flex items-center gap-1">
                <SearchTool value={search} onChange={library.setSearch} />
                <FilterTool
                  tab={tab}
                  typeFilter={typeFilter}
                  onTypeFilter={library.setTypeFilter}
                  sort={library.sort}
                  onSort={library.setSort}
                />
                <ViewTool view={view} onToggle={() => library.setView(view === "grid" ? "list" : "grid")} />
              </div>
            </div>
          )}

          {newRow && (
            <section aria-labelledby="nodes-new-heading" className="mt-9">
              <h2 id="nodes-new-heading" className="mb-3.5 text-base text-muted-foreground">
                {t("nodes.new.heading")}
              </h2>
              <NewNodeRow onPick={setNewType} />
            </section>
          )}

          <div className={newRow ? "mt-10" : "mt-8"}>
            {failed ? (
              <QuietState testId="nodes-error" tone="error" sentence={t("nodes.states.error")}>
                <Button variant="outline" size="sm" onClick={() => void library.nodes.refetch()}>
                  {t("nodes.states.retry")}
                </Button>
              </QuietState>
            ) : loading ? (
              <SkeletonGrid label={t("nodes.states.loading")} />
            ) : shown.length === 0 ? (
              newRow ? (
                <QuietState testId="nodes-empty" sentence={t("nodes.states.empty")} />
              ) : (
                <QuietState testId="nodes-no-matches" sentence={emptySentence(library, t)}>
                  <Button variant="outline" size="sm" onClick={library.showAll} data-testid="nodes-show-all">
                    {t("nodes.states.show_all")}
                  </Button>
                </QuietState>
              )
            ) : view === "list" ? (
              <NodeList cards={shown} favorites={library.favorites} actions={actions} library={library} onOpen={open} />
            ) : (
              <NodeGrid cards={shown} favorites={library.favorites} actions={actions} library={library} onOpen={open} />
            )}

            {!loading && !failed && skippedRuns > 0 && (tab === "all" || tab === "runs") && (
              <p className="pt-10 text-sm text-muted-foreground">
                {t("nodes.states.older_not_scanned").replace("{0}", String(scannedRuns))}
              </p>
            )}
          </div>
        </div>
      </ScrollArea>

      {actions.layer}
      <NewNodeDialog
        type={newType}
        onClose={() => setNewType(null)}
        onRequested={library.addPending}
        onCreated={onOpen}
      />
    </div>
  );
}

/** Why the current tab, search or filter shows nothing. */
function emptySentence(library: NodesLibraryState, t: Translate): string {
  const query = library.search.trim();
  if (query !== "") return t("nodes.states.no_matches").replace("{0}", () => query);
  if (typeFilterApplies(library.tab, library.typeFilter)) {
    return t("nodes.states.no_type").replace("{0}", () => t(NODE_TYPE_LABEL_KEY[library.typeFilter as NodeType]));
  }
  return t(`nodes.states.empty_${library.tab}`);
}

/* --- the header row ------------------------------------------------------- */

function LibraryTabs({
  tab,
  counts,
  showCounts,
  onChange,
}: {
  tab: LibraryTab;
  counts: Record<LibraryTab, number>;
  /** No answer yet: counts are left out rather than shown as zeros. */
  showCounts: boolean;
  onChange: (next: LibraryTab) => void;
}) {
  const t = useT();
  return (
    <div role="group" aria-label={t("nodes.tabs.label")} className="-ml-3 flex flex-wrap items-center gap-1">
      {LIBRARY_TABS.map((id) => {
        const active = tab === id;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(id)}
            data-testid={`nodes-tab-${id}`}
            data-count={showCounts ? counts[id] : undefined}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-base font-medium transition-colors duration-fast",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-secondary text-foreground-strong" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`nodes.tabs.${id}`)}
            {showCounts && id !== "all" && counts[id] > 0 && (
              <span className="text-sm font-normal tabular-nums text-muted-foreground">{counts[id]}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Search: a bare icon until it is asked for, then a field in the same place.
 * Escape (or the cross) closes it and clears the search; left empty, it
 * folds back by itself.
 */
function SearchTool({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const t = useT();
  const [open, setOpen] = useState(value !== "");
  const field = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  /** Closed on purpose (Escape, the cross): focus goes back to the icon. */
  const returnFocus = useRef(false);

  useEffect(() => {
    if (open) field.current?.focus();
    else if (returnFocus.current) button.current?.focus();
    returnFocus.current = false;
  }, [open]);

  // The field follows a search set elsewhere: there is one to show, or it
  // was cleared ("Show all") while nobody was typing.
  useEffect(() => {
    if (value !== "") setOpen(true);
    else if (document.activeElement !== field.current) setOpen(false);
  }, [value]);

  const close = () => {
    returnFocus.current = true;
    onChange("");
    setOpen(false);
  };

  if (!open) {
    return (
      <QuickTooltip content={t("nodes.search.open")} side="bottom" className="inline-flex">
        <button
          ref={button}
          type="button"
          aria-label={t("nodes.search.open")}
          onClick={() => setOpen(true)}
          data-testid="nodes-search"
          className={TOOL_BUTTON}
        >
          <Search aria-hidden />
        </button>
      </QuickTooltip>
    );
  }
  return (
    <div className="relative w-56 max-w-full sm:w-64">
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        ref={field}
        type="text"
        role="searchbox"
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          close();
        }}
        onBlur={() => {
          if (value.trim() === "") setOpen(false);
        }}
        placeholder={t("nodes.search.placeholder")}
        aria-label={t("nodes.search.placeholder")}
        data-testid="nodes-search-field"
        className={cn(
          "h-8 w-full rounded-md border border-border-strong bg-input pl-8 pr-8 text-base text-foreground",
          "placeholder:text-foreground-faint transition-colors duration-fast",
          "focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      />
      <button
        type="button"
        aria-label={t("nodes.search.close")}
        // Keep the field's blur from folding the tool before the click lands.
        onMouseDown={(event) => event.preventDefault()}
        onClick={close}
        data-testid="nodes-search-close"
        className="absolute right-1 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-muted-foreground transition-colors duration-fast hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}

/**
 * Filter and order: a small panel under its button. One type or all of them
 * (not on the "Runs" tab: a run has no node type), and one of three orders.
 */
function FilterTool({
  tab,
  typeFilter,
  onTypeFilter,
  sort,
  onSort,
}: {
  tab: LibraryTab;
  typeFilter: TypeFilter;
  onTypeFilter: (next: TypeFilter) => void;
  sort: LibrarySort;
  onSort: (next: LibrarySort) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const filtering = typeFilterApplies(tab, typeFilter);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) root.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close(true);
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    // The choice in force is where the keys start.
    const items = panel.current?.querySelectorAll<HTMLButtonElement>("[role='menuitemradio']");
    const start = [...(items ?? [])].find((item) => item.getAttribute("aria-checked") === "true") ?? items?.[0];
    start?.focus({ preventScroll: true });
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open, close]);

  const onPanelKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>("[role='menuitemradio']") ?? []);
    if (!items.length) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  };

  const choose = (apply: () => void) => () => {
    apply();
    close(true);
  };

  return (
    <div
      ref={root}
      className="relative"
      onBlur={(event) => {
        // Tab out of the panel: it closes behind the reader.
        if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <QuickTooltip content={open ? "" : t("nodes.filter.label")} side="bottom" className="inline-flex">
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={t("nodes.filter.label")}
          onClick={() => setOpen((value) => !value)}
          data-testid="nodes-filter"
          data-active={filtering || undefined}
          className={cn(TOOL_BUTTON, (open || filtering) && "text-foreground", open && "bg-secondary")}
        >
          <ListFilter aria-hidden />
          {filtering && (
            <span aria-hidden className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />
          )}
        </button>
      </QuickTooltip>
      {open && (
        <div
          ref={panel}
          role="menu"
          aria-label={t("nodes.filter.label")}
          onKeyDown={onPanelKeyDown}
          // A press inside must not move the focus: a WebView that does not
          // focus a clicked button would blur the panel shut before the click.
          onMouseDown={(event) => event.preventDefault()}
          data-testid="nodes-filter-panel"
          className={cn(
            "absolute right-0 top-full z-50 mt-2 w-60 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float",
            "animate-in fade-in-0 zoom-in-95 duration-fast motion-reduce:animate-none",
          )}
        >
          {tab !== "runs" && (
            <>
              <div role="group" aria-label={t("nodes.filter.type_heading")}>
                <PanelHeading>{t("nodes.filter.type_heading")}</PanelHeading>
                <PanelChoice
                  chosen={typeFilter === "all"}
                  testId="nodes-filter-type-all"
                  icon={<Shapes className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                  onChoose={choose(() => onTypeFilter("all"))}
                >
                  {t("nodes.filter.all_types")}
                </PanelChoice>
                {NODE_TYPES.map((type) => (
                  <PanelChoice
                    key={type}
                    chosen={typeFilter === type}
                    testId={`nodes-filter-type-${type}`}
                    icon={<NodeTypeIcon type={type} className="h-4 w-4 shrink-0 text-muted-foreground" />}
                    onChoose={choose(() => onTypeFilter(type))}
                  >
                    {t(NODE_TYPE_LABEL_KEY[type])}
                  </PanelChoice>
                ))}
              </div>
              <div role="separator" className="mx-1 my-1 h-px bg-border" />
            </>
          )}
          <div role="group" aria-label={t("nodes.filter.sort_heading")}>
            <PanelHeading>{t("nodes.filter.sort_heading")}</PanelHeading>
            {LIBRARY_SORTS.map((id) => (
              <PanelChoice
                key={id}
                chosen={sort === id}
                testId={`nodes-sort-${id}`}
                onChoose={choose(() => onSort(id))}
              >
                {t(`nodes.filter.sort_${id}`)}
              </PanelChoice>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PanelHeading({ children }: { children: ReactNode }) {
  return <p className="px-2.5 pb-1 pt-1.5 text-sm text-muted-foreground">{children}</p>;
}

/** One choice of a single-choice list; the chosen one carries a check. */
function PanelChoice({
  chosen,
  onChoose,
  testId,
  icon,
  children,
}: {
  chosen: boolean;
  onChoose: () => void;
  testId: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={chosen}
      onClick={onChoose}
      data-testid={testId}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-base transition-colors duration-fast",
        "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none",
        chosen ? "font-medium text-foreground-strong" : "text-foreground",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {chosen && <Check className="h-4 w-4 shrink-0 text-foreground" aria-hidden />}
    </button>
  );
}

/** Grid or list: the button shows the view it switches to. */
function ViewTool({ view, onToggle }: { view: "grid" | "list"; onToggle: () => void }) {
  const t = useT();
  const label = t(view === "grid" ? "nodes.view.to_list" : "nodes.view.to_grid");
  return (
    <QuickTooltip content={label} side="bottom" className="inline-flex">
      <button
        type="button"
        aria-label={label}
        onClick={onToggle}
        data-testid="nodes-view-toggle"
        data-view={view}
        className={TOOL_BUTTON}
      >
        {view === "grid" ? <List aria-hidden /> : <LayoutGrid aria-hidden />}
      </button>
    </QuickTooltip>
  );
}

/* --- states --------------------------------------------------------------- */

/** One quiet sentence where the cards would be, and at most one way on. */
function QuietState({
  sentence,
  tone = "plain",
  testId,
  children,
}: {
  sentence: string;
  tone?: "plain" | "error";
  testId: string;
  children?: ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      role={tone === "error" ? "alert" : undefined}
      className="flex min-h-48 flex-col items-center justify-center gap-4 px-4 py-10 text-center"
    >
      <p className="max-w-md text-base text-muted-foreground">{sentence}</p>
      {children}
    </div>
  );
}

/** Six cards of the real size, so nothing jumps when the library answers. */
function SkeletonGrid({ label }: { label: string }) {
  return (
    <div role="status" aria-busy="true" aria-label={label} data-testid="nodes-skeleton" className={GRID_CLASS}>
      {Array.from({ length: SKELETON_CARDS }, (_, index) => (
        <div key={index} aria-hidden className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="aspect-[2/1.02] w-full animate-pulse bg-sheen/[0.06] motion-reduce:animate-none" />
          <div className="px-5 pb-[18px] pt-4">
            <span className="block h-6 py-1">
              <span className="block h-4 w-3/5 rounded bg-sheen/[0.06]" />
            </span>
            <span className="mt-1 block h-[18px] py-[3px]">
              <span className="block h-3 w-2/5 rounded bg-sheen/[0.06]" />
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* --- cards ---------------------------------------------------------------- */

interface CardListProps {
  cards: NodeCard[];
  favorites: ReadonlySet<string>;
  actions: NodeCardActions;
  library: NodesLibraryState;
  onOpen: (card: NodeCard) => void;
}

const ARROW_KEYS = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];

/**
 * The card an arrow key leads to. Left and right walk the reading order; up
 * and down go to the card in the next row whose middle is closest, read from
 * where the cards really are, so it holds for any number of columns.
 */
function neighbourCard(items: HTMLElement[], current: HTMLElement, key: string): HTMLElement | null {
  const index = items.indexOf(current);
  if (index < 0) return null;
  if (key === "Home") return items[0] ?? null;
  if (key === "End") return items[items.length - 1] ?? null;
  if (key === "ArrowLeft") return items[index - 1] ?? null;
  if (key === "ArrowRight") return items[index + 1] ?? null;
  const down = key === "ArrowDown";
  const here = current.getBoundingClientRect();
  // Without a layout (a test DOM) every card sits at the origin: walk the order.
  if (here.width === 0) return items[index + (down ? 1 : -1)] ?? null;
  const beyond = items
    .map((element) => ({ element, box: element.getBoundingClientRect() }))
    .filter(({ box }) => (down ? box.top > here.top + 1 : box.top < here.top - 1));
  if (beyond.length === 0) return null;
  const rowTop = down
    ? Math.min(...beyond.map(({ box }) => box.top))
    : Math.max(...beyond.map(({ box }) => box.top));
  const middle = here.left + here.width / 2;
  let best: HTMLElement | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const { element, box } of beyond) {
    if (Math.abs(box.top - rowTop) > 1) continue;
    const distance = Math.abs(box.left + box.width / 2 - middle);
    if (distance < bestDistance) {
      best = element;
      bestDistance = distance;
    }
  }
  return best;
}

/** Arrow keys move the focus from card to card inside `container`. */
function onCardsKeyDown(event: ReactKeyboardEvent<HTMLElement>, columns: boolean): void {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (!ARROW_KEYS.includes(event.key)) return;
  if (!columns && (event.key === "ArrowLeft" || event.key === "ArrowRight")) return;
  const current = (event.target as HTMLElement).closest<HTMLElement>("[data-node-key]");
  if (!current || current !== event.target) return;
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[data-node-key]"));
  const next = neighbourCard(items, current, event.key);
  event.preventDefault();
  next?.focus();
}

/** What a card shares between the grid and the list: its keys, its menu, its drag. */
function useCardInteractions(
  card: NodeCard,
  actions: NodeCardActions,
  onToggleFavorite: (key: string) => void,
  onOpen: (card: NodeCard) => void,
) {
  const pending = isPendingCard(card);
  const client = useQueryClient();

  // Every card that stands for a run can be dragged onto the assistant's
  // dock: the run is what the dock takes. The run itself (its state, its
  // summary, its mission) is in the run list the stage keeps; the card's own
  // few facts stand in when that list has not been read.
  const dragProps =
    pending || card.slug === ""
      ? {}
      : {
          draggable: true,
          onDragStart: (event: DragEvent) => {
            const runs = client.getQueryData<OutputSummary[]>(["outputs"]);
            const run = runs?.find((candidate) => candidate.slug === card.slug);
            startMissionDrag(
              event,
              run ?? {
                slug: card.slug,
                utterance: card.request || card.title,
                status:
                  card.status === "building"
                    ? "running"
                    : card.status === "error"
                      ? "error"
                      : "success",
                summary: "",
                error: "",
                mission_id: null,
              },
            );
          },
          onDragEnd: endMissionDrag,
        };

  const onContextMenu = (event: ReactMouseEvent<HTMLElement>) => {
    // The app-wide Cut/Copy/Paste menu lives on document; a card offers its
    // own actions instead. The menu key reports no pointer, so the menu then
    // opens at the card's corner.
    event.preventDefault();
    event.stopPropagation();
    if (event.clientX === 0 && event.clientY === 0) {
      const box = event.currentTarget.getBoundingClientRect();
      actions.openMenu(card, box.left + 16, box.top + 16, event.currentTarget);
    } else {
      actions.openMenu(card, event.clientX, event.clientY, event.currentTarget);
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (pending || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "Enter") {
      // Said outright rather than left to the button's own click, so Enter
      // opens the card whatever the cover inside it does with the key.
      event.preventDefault();
      onOpen(card);
    } else if (event.key === "Delete") {
      event.preventDefault();
      actions.askDelete(card);
    } else if (event.key === "f" || event.key === "F") {
      event.preventDefault();
      onToggleFavorite(card.key);
    }
  };

  /** The "more" button: the same menu, hung under the button's right edge. */
  const onMore = (event: ReactMouseEvent<HTMLElement>) => {
    event.stopPropagation();
    const box = event.currentTarget.getBoundingClientRect();
    actions.openMenu(card, box.right - NODE_MENU_WIDTH, box.bottom + 6, event.currentTarget);
  };

  return { pending, dragProps, onContextMenu, onKeyDown, onMore };
}

/** What a card says about itself besides its date: being built, failed, kept current. */
function CardState({ card }: { card: NodeCard }) {
  const t = useT();
  if (cardIsWorking(card)) {
    return (
      <span className="inline-flex min-w-0 items-center gap-1.5" data-testid="node-card-state" data-state="building">
        <Loader2 className="h-3 w-3 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
        <span className="truncate">{t("nodes.card.building")}</span>
      </span>
    );
  }
  if (card.status === "error") {
    return (
      <span className="inline-flex min-w-0 items-center gap-1.5" data-testid="node-card-state" data-state="error">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-destructive" aria-hidden />
        <span className="truncate">{t("nodes.card.failed")}</span>
      </span>
    );
  }
  if (!card.kept_current) return null;
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5"
      data-testid="node-card-state"
      data-state={card.refreshing ? "kept" : "paused"}
    >
      <span
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", card.refreshing ? "bg-success" : "bg-foreground-faint")}
        aria-hidden
      />
      <span className="truncate">{t(card.refreshing ? "nodes.card.kept_current" : "nodes.card.paused")}</span>
    </span>
  );
}

function FavoriteButton({
  favorite,
  onToggle,
  className,
}: {
  favorite: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const t = useT();
  const label = t(favorite ? "nodes.menu.favorite_remove" : "nodes.menu.favorite_add");
  return (
    <button
      type="button"
      aria-pressed={favorite}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      data-testid="node-card-star"
      className={cn(CARD_BUTTON, className)}
    >
      <Star className={cn(favorite && "fill-current text-warning")} aria-hidden />
    </button>
  );
}

function MoreButton({
  open,
  onClick,
  className,
}: {
  open: boolean;
  onClick: (event: ReactMouseEvent<HTMLElement>) => void;
  className?: string;
}) {
  const t = useT();
  return (
    <button
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={t("nodes.menu.aria")}
      onClick={onClick}
      data-testid="node-card-menu"
      data-open={open}
      className={cn(CARD_BUTTON, className)}
    >
      <Ellipsis aria-hidden />
    </button>
  );
}

function NodeGrid({ cards, favorites, actions, library, onOpen }: CardListProps) {
  return (
    <div data-testid="nodes-grid" className={GRID_CLASS} onKeyDown={(event) => onCardsKeyDown(event, true)}>
      {cards.map((card) => (
        <GridCard
          key={card.key}
          card={card}
          favorite={favorites.has(card.key)}
          menuOpen={actions.menuKey === card.key}
          actions={actions}
          onToggleFavorite={library.toggleFavorite}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

interface CardProps {
  card: NodeCard;
  favorite: boolean;
  menuOpen: boolean;
  actions: NodeCardActions;
  onToggleFavorite: (key: string) => void;
  onOpen: (card: NodeCard) => void;
}

/** One card: the cover, and under it the name, the date, the state and the type. */
function GridCard({ card, favorite, menuOpen, actions, onToggleFavorite, onOpen }: CardProps) {
  const t = useT();
  const locale = useRunLocale();
  const { pending, dragProps, onContextMenu, onKeyDown, onMore } = useCardInteractions(
    card,
    actions,
    onToggleFavorite,
    onOpen,
  );
  const typeName = t(NODE_TYPE_LABEL_KEY[card.type]);
  const when = cardIsWorking(card) ? "" : cardWhen(card.updated_at, Date.now(), locale, t("nodes.card.today"));
  // On imagery of any color the corner buttons need their own ground.
  const onCover = "border border-border bg-popover shadow-rim hover:bg-popover";

  return (
    // The hover target stays where it is and its content rises, so a pointer
    // resting on the lower edge does not fall off the card it just lifted.
    <div className="group/card min-w-0">
      <div
        className={cn(
          "relative rounded-lg transition-transform duration-base ease-out-soft",
          !pending && "motion-safe:group-hover/card:-translate-y-0.5",
        )}
      >
        <button
          type="button"
          onClick={() => onOpen(card)}
          onContextMenu={pending ? undefined : onContextMenu}
          onKeyDown={onKeyDown}
          aria-disabled={pending || undefined}
          data-testid="node-card"
          data-node-key={card.key}
          data-node-type={card.type}
          data-origin={card.origin}
          data-status={card.status}
          className={cn(
            "block w-full overflow-hidden rounded-lg border border-border bg-card text-left",
            "transition-[border-color,box-shadow] duration-base ease-out-soft",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            pending
              ? "cursor-default"
              : "group-hover/card:border-border-strong group-hover/card:shadow-float",
          )}
          {...dragProps}
        >
          <NodeCover card={card} className="w-full" />
          <span className="block px-5 pb-[18px] pt-4">
            <span className="block truncate text-lg font-medium text-foreground-strong">{card.title}</span>
            <span className="mt-1 flex h-[18px] items-center gap-1.5 text-sm text-muted-foreground">
              {when && <span className="shrink-0 whitespace-nowrap">{when}</span>}
              {when && (card.kept_current || card.status === "error") && <span aria-hidden>·</span>}
              <CardState card={card} />
              <QuickTooltip content={typeName} side="top" className="ml-auto inline-flex shrink-0 pl-2">
                <NodeTypeIcon type={card.type} className="h-4 w-4" />
                <span className="sr-only">{typeName}</span>
              </QuickTooltip>
            </span>
          </span>
        </button>

        {!pending && (
          <div className="absolute right-2.5 top-2.5 flex items-center gap-1.5">
            <FavoriteButton
              favorite={favorite}
              onToggle={() => onToggleFavorite(card.key)}
              className={cn(onCover, !favorite && REVEALED_ON_CARD)}
            />
            <MoreButton open={menuOpen} onClick={onMore} className={cn(onCover, REVEALED_ON_CARD)} />
          </div>
        )}
      </div>
    </div>
  );
}

/** The same cards as rows: a thumbnail, the name, the type, the state, the date. */
function NodeList({ cards, favorites, actions, library, onOpen }: CardListProps) {
  return (
    <div
      data-testid="nodes-list"
      className="divide-y divide-border border-y border-border"
      onKeyDown={(event) => onCardsKeyDown(event, false)}
    >
      {cards.map((card) => (
        <ListRow
          key={card.key}
          card={card}
          favorite={favorites.has(card.key)}
          menuOpen={actions.menuKey === card.key}
          actions={actions}
          onToggleFavorite={library.toggleFavorite}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function ListRow({ card, favorite, menuOpen, actions, onToggleFavorite, onOpen }: CardProps) {
  const t = useT();
  const locale = useRunLocale();
  const { pending, dragProps, onContextMenu, onKeyDown, onMore } = useCardInteractions(
    card,
    actions,
    onToggleFavorite,
    onOpen,
  );
  const typeName = t(NODE_TYPE_LABEL_KEY[card.type]);
  const when = cardIsWorking(card) ? "" : cardWhen(card.updated_at, Date.now(), locale, t("nodes.card.today"));
  const quiet = "hover:bg-secondary";

  return (
    <div
      className={cn(
        "group/card flex items-center gap-1 pr-1 transition-colors duration-fast",
        !pending && "hover:bg-card focus-within:bg-card",
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(card)}
        onContextMenu={pending ? undefined : onContextMenu}
        onKeyDown={onKeyDown}
        aria-disabled={pending || undefined}
        data-testid="node-card"
        data-node-key={card.key}
        data-node-type={card.type}
        data-origin={card.origin}
        data-status={card.status}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-4 rounded-md py-2.5 pl-2 pr-2 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          pending && "cursor-default",
        )}
        {...dragProps}
      >
        <NodeCover card={card} className="aspect-auto h-14 w-[88px] shrink-0 rounded-md border border-border" />
        <span className="min-w-0 flex-1 truncate text-lg font-medium text-foreground-strong">{card.title}</span>
        <span className="hidden w-28 shrink-0 items-center gap-2 text-sm text-muted-foreground lg:flex">
          <NodeTypeIcon type={card.type} className="h-4 w-4 shrink-0" />
          <span className="truncate">{typeName}</span>
        </span>
        <span className="hidden w-36 shrink-0 text-sm text-muted-foreground md:flex">
          <CardState card={card} />
        </span>
        <span className="w-24 shrink-0 truncate text-right text-sm tabular-nums text-muted-foreground">{when}</span>
      </button>
      {pending ? (
        <span aria-hidden className="w-[68px] shrink-0" />
      ) : (
        <>
          <FavoriteButton
            favorite={favorite}
            onToggle={() => onToggleFavorite(card.key)}
            className={cn(quiet, !favorite && REVEALED_ON_CARD)}
          />
          <MoreButton open={menuOpen} onClick={onMore} className={cn(quiet, REVEALED_ON_CARD)} />
        </>
      )}
    </div>
  );
}
