/**
 * The starter list: a search, one round chip per area with its live count,
 * and plain rows (the name, the outcome in one line). Arrow keys move through
 * the rows; the picked row carries the selection wash.
 */
import { useMemo, useRef, type KeyboardEvent } from "react";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useT } from "@/i18n";
import { areaCounts, filterStarters, starterCopy, type AreaFilter } from "./starterFilters";
import type { Starter, StarterArea } from "./startersApi";

interface Props {
  starters: Starter[];
  areas: StarterArea[];
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  area: AreaFilter;
  onAreaChange: (area: AreaFilter) => void;
  query: string;
  onQueryChange: (query: string) => void;
  selectedId: string | null;
  onSelect: (starter: Starter) => void;
}

export function StarterGallery(props: Props) {
  const t = useT();
  const rows = useRef<(HTMLButtonElement | null)[]>([]);
  const copyOf = useMemo(() => {
    const cache = new Map<string, ReturnType<typeof starterCopy>>();
    return (starter: Starter) => {
      let copy = cache.get(starter.id);
      if (!copy) {
        copy = starterCopy(t, starter);
        cache.set(starter.id, copy);
      }
      return copy;
    };
  }, [t]);
  const shown = useMemo(
    () => filterStarters(props.starters, props.area, props.query, copyOf),
    [props.starters, props.area, props.query, copyOf],
  );
  const counts = useMemo(
    () => areaCounts(props.starters, props.areas, props.query, copyOf),
    [props.starters, props.areas, props.query, copyOf],
  );
  const chips: AreaFilter[] = ["all", ...props.areas];
  // One row is always reachable with Tab, even when the picked starter is filtered out.
  const selectedShown = shown.some((starter) => starter.id === props.selectedId);

  function onRowKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = Math.min(shown.length - 1, Math.max(0, index + step));
    rows.current[next]?.focus();
    props.onSelect(shown[next]);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-testid="starter-gallery">
      <div className="cs-search">
        <Input
          value={props.query}
          onChange={(event) => props.onQueryChange(event.target.value)}
          placeholder={t("agent_create.gallery.search")}
          aria-label={t("agent_create.gallery.search")}
          data-testid="starter-search"
        />
      </div>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("agent_create.gallery.areas")}>
        {chips.map((area) => {
          const on = props.area === area;
          return (
            <button
              key={area}
              type="button"
              aria-pressed={on}
              onClick={() => props.onAreaChange(area)}
              data-testid={`starter-area-${area}`}
              className="cs-chip"
            >
              {t(`agent_create.area.${area}`)}
              <span className="cs-chip-count">{counts[area] ?? 0}</span>
            </button>
          );
        })}
      </div>

      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1" role="listbox" aria-label={t("agent_create.mode.starter")}>
        {props.loading ? (
          <p className="flex items-center gap-2 px-2 py-6 text-sm text-muted-foreground" role="status">
            <Loader2 className="size-4 animate-spin" aria-hidden /> {t("agent_create.gallery.loading")}
          </p>
        ) : props.failed ? (
          <div className="flex flex-col items-start gap-2 px-2 py-6 text-sm">
            <p role="alert" className="text-destructive">{t("agent_create.gallery.failed")}</p>
            <button type="button" onClick={props.onRetry} className="cs-btn" data-variant="soft" data-size="sm">
              {t("agent_create.gallery.retry")}
            </button>
          </div>
        ) : shown.length === 0 ? (
          <p className="px-2 py-6 text-sm text-muted-foreground" data-testid="starter-empty">{t("agent_create.gallery.empty")}</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {shown.map((starter, index) => {
              const copy = copyOf(starter);
              const selected = starter.id === props.selectedId;
              return (
                <li key={starter.id}>
                  <button
                    ref={(node) => { rows.current[index] = node; }}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    tabIndex={selected || (!selectedShown && index === 0) ? 0 : -1}
                    onClick={() => props.onSelect(starter)}
                    onKeyDown={(event) => onRowKey(event, index)}
                    data-testid={`starter-${starter.id}`}
                    className="cs-row"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="cs-row-name">{copy.name}</span>
                      <span className="cs-row-detail">{copy.outcome}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
