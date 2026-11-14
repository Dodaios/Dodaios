/**
 * What the new-node dialog asks for an Analytics node beyond its subject.
 *
 * An analysis is made from data, so the dialog asks where the data comes
 * from (a file, Notion, a sheet, a shop, a portfolio, prices from the web:
 * free text, with a few common sources one click away), and whether the
 * assistant should keep it current and how often. Both go into the request
 * the dialog sends; the assistant reads the sources and, when asked to keep
 * the analysis current, schedules the refresh with them.
 */
import { useRef } from "react";
import { RefreshCw } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { nodeHueStyle } from "./nodeTheme";

/** How often a kept-current analysis may check its sources, in minutes. */
export const ANALYTICS_CADENCES = [15, 60, 180, 1440] as const;
export type AnalyticsCadence = (typeof ANALYTICS_CADENCES)[number];

/** The common sources offered as one-click chips (`nodes.new.data.chips.<id>`). */
const SOURCE_CHIPS = ["file", "notion", "sheets", "shop", "portfolio", "web"] as const;
/** How often a kept-current analysis checks its sources unless the reader picks another. */
export const DEFAULT_ANALYTICS_CADENCE: AnalyticsCadence = 60;

export interface AnalyticsFieldsProps {
  sources: string;
  onSources: (sources: string) => void;
  live: boolean;
  onLive: (live: boolean) => void;
  every: AnalyticsCadence;
  onEvery: (every: AnalyticsCadence) => void;
  disabled: boolean;
}

/** `sources` with `name` added as one more item of the list. */
export function withSource(sources: string, name: string): string {
  const current = sources.trim();
  if (current === "") return name;
  const listed = current.split(/\s*[,;\n]\s*/).map((item) => item.toLowerCase());
  if (listed.includes(name.toLowerCase())) return current;
  return `${current.replace(/[,;]$/, "")}, ${name}`;
}

export function AnalyticsFields({
  sources,
  onSources,
  live,
  onLive,
  every,
  onEvery,
  disabled,
}: AnalyticsFieldsProps) {
  const t = useT();
  const field = useRef<HTMLTextAreaElement>(null);

  return (
    <div data-testid="new-node-analytics" style={nodeHueStyle("data")}>
      <label htmlFor="new-node-sources" className="mt-5 block text-base font-medium text-foreground">
        {t("nodes.new.data.sources_label")}
      </label>
      <Textarea
        id="new-node-sources"
        ref={field}
        rows={2}
        value={sources}
        disabled={disabled}
        placeholder={t("nodes.new.data.sources_placeholder")}
        onChange={(event) => onSources(event.target.value)}
        aria-describedby="new-node-sources-hint"
        data-testid="new-node-sources"
        className="mt-2 min-h-[64px] resize-none"
      />
      <p id="new-node-sources-hint" className="mt-1.5 text-sm text-muted-foreground">
        {t("nodes.new.data.sources_hint")}
      </p>
      <ul aria-label={t("nodes.new.data.chips_label")} className="mt-2.5 flex flex-wrap gap-2">
        {SOURCE_CHIPS.map((id) => {
          const name = t(`nodes.new.data.chips.${id}`);
          return (
            <li key={id}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  onSources(withSource(sources, name));
                  field.current?.focus();
                }}
                data-testid="new-node-source-chip"
                className="rounded-full border border-dashed border-border px-3 py-1 text-sm text-muted-foreground transition-colors duration-fast hover:border-border-strong hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              >
                + {name}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-5 rounded-lg border border-border px-4 py-3">
        <div className="flex items-start gap-3">
          <RefreshCw aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <label htmlFor="new-node-live" className="block text-base font-medium text-foreground">
              {t("nodes.new.data.live_label")}
            </label>
            <p className="text-sm text-muted-foreground">{t("nodes.new.data.live_detail")}</p>
          </div>
          <Switch
            id="new-node-live"
            checked={live}
            disabled={disabled}
            onCheckedChange={onLive}
            data-testid="new-node-live"
            className="mt-0.5"
          />
        </div>
        {live && (
          <div
            role="radiogroup"
            aria-label={t("nodes.new.data.every_label")}
            className="mt-3 flex flex-wrap gap-1.5 pl-7"
            data-testid="new-node-every"
          >
            {ANALYTICS_CADENCES.map((minutes) => {
              const chosen = minutes === every;
              return (
                <button
                  key={minutes}
                  type="button"
                  role="radio"
                  aria-checked={chosen}
                  disabled={disabled}
                  onClick={() => onEvery(minutes)}
                  data-testid={`new-node-every-${minutes}`}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-sm transition-colors duration-fast",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
                    chosen
                      ? "border-[hsl(var(--node-hue)/0.5)] bg-[hsl(var(--node-hue)/0.14)] text-foreground-strong"
                      : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                  )}
                >
                  {t(`nodes.new.data.every.${minutes}`)}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
