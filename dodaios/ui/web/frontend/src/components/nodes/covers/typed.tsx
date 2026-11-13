/**
 * The miniatures of the typed nodes, drawn from a card's `preview`: a page of
 * a document, a small table, a dashboard, a first slide, a board with sticky
 * notes, a film frame, and the first lines of a run's answer.
 *
 * The text in them is real text at small sizes: a picture of the node made of
 * its own words, clipped by the paper. That is why these files use sizes
 * below the app's type floor; nothing here is meant to be read at length.
 * Every value is rendered as a React text node, never as markup.
 */
import type { CSSProperties } from "react";

import type {
  DataPreview,
  DocsPreview,
  MotionPreview,
  OutputPreview,
  SheetsPreview,
  SlidesPreview,
  WhiteboardColor,
  WhiteboardPreview,
} from "../nodeModel";
import { Artboard, CoverPill, Paper, TextBars, arr, num, str } from "./kit";

const HUE = "hsl(var(--node-hue))";

/*
 * The two sizes of miniature text. They grow a little with the card (the
 * cover is the size container), so a wide card's paper is not left half
 * empty, and stop at 12 and 15 px: it stays a picture of text.
 */
const MINI_TEXT = "text-[clamp(10px,2.75cqw,12px)]";
const MINI_HEADING = "text-[clamp(12px,3.4cqw,15px)]";

/* --- docs ------------------------------------------------------------------ */

export function DocsMini({ preview }: { preview: DocsPreview | null }) {
  const heading = str(preview?.heading).trim();
  const lines = arr(preview?.lines)
    .map((line) => str(line).trim())
    .filter((line) => line !== "")
    .slice(0, 7);
  const bullets = preview?.bullets === true;
  return (
    <Paper>
      <div data-node-mini="docs" className="px-[10%] pt-[9%]">
        {heading !== "" && (
          <p className={`truncate font-display leading-[1.35] text-foreground-strong ${MINI_HEADING}`}>{heading}</p>
        )}
        {lines.length > 0 ? (
          <ul className={heading !== "" ? "mt-[6px] flex flex-col gap-[3px]" : "flex flex-col gap-[3px]"}>
            {lines.map((line, index) => (
              <li key={index} className={`flex gap-[5px] leading-[1.4] text-muted-foreground ${MINI_TEXT}`}>
                {bullets && (
                  <span className="mt-[0.55em] h-[3px] w-[3px] shrink-0 rounded-full bg-foreground-faint" />
                )}
                <span className={bullets ? "min-w-0 truncate" : "line-clamp-2 min-w-0 [overflow-wrap:anywhere]"}>
                  {line}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <TextBars heading={heading === ""} className={heading !== "" ? "mt-[9px]" : undefined} />
        )}
      </div>
    </Paper>
  );
}

/* --- sheets ---------------------------------------------------------------- */

/*
 * `[@container(max-width:340px)]:` applies while the cover (the size
 * container) is a narrow one. The classes are written out in full wherever
 * they are used: Tailwind finds class names by reading the source text.
 */

const SHEET_MAX_COLUMNS = 4;
/** The grid per column count: the first column a little wider than the rest. */
const SHEET_COLUMNS = [
  "grid-cols-[minmax(0,1fr)]",
  "grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]",
  "grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]",
  "grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] [@container(max-width:340px)]:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]",
];
const SHEET_MAX_ROWS = 3;
const SHEET_ROW_HEIGHT = 20;
const SHEET_CELL = "h-[20px] truncate px-[6px] text-[10px] leading-[20px]";
/**
 * The sheet's horizontal rules, drawn as one repeating ground: the grid runs
 * on down the paper like a real sheet, however tall the card is, and the
 * empty rows cost no elements.
 */
const SHEET_RULES: CSSProperties = {
  backgroundImage: `repeating-linear-gradient(to bottom, transparent 0, transparent ${SHEET_ROW_HEIGHT - 1}px, hsl(var(--border)) ${SHEET_ROW_HEIGHT - 1}px, hsl(var(--border)) ${SHEET_ROW_HEIGHT}px)`,
};

export function SheetsMini({ preview }: { preview: SheetsPreview | null }) {
  const columns = arr(preview?.columns).map(str);
  const rows = arr(preview?.rows)
    .slice(0, SHEET_MAX_ROWS)
    .map((row) => arr(row).map(str));
  const widest = Math.max(columns.length, ...rows.map((row) => row.length));
  const count = Math.min(SHEET_MAX_COLUMNS, widest > 0 ? widest : 3);
  const numeric = arr(preview?.numeric);
  const indexes = Array.from({ length: count }, (_, index) => index);
  // Every column but the last draws the line to its right. A narrow card
  // shows three columns: the fourth goes, and the third becomes the last.
  const edge = (index: number) => {
    if (index === 3) return " [@container(max-width:340px)]:hidden";
    if (index === count - 1) return "";
    return index === 2 ? " border-r [@container(max-width:340px)]:border-r-0" : " border-r";
  };
  return (
    <Paper>
      <div data-node-mini="sheets" className={`grid h-full ${SHEET_COLUMNS[count - 1]}`} style={SHEET_RULES}>
        {indexes.map((index) => (
          <div
            key={index}
            className={`min-w-0 border-border${edge(index)}${numeric[index] === true ? " text-right tabular-nums" : ""}`}
          >
            <div className={`${SHEET_CELL} bg-foreground/[0.045] font-medium text-foreground-secondary`}>
              {columns[index] ?? ""}
            </div>
            {rows.map((row, rowIndex) => (
              <div
                key={rowIndex}
                className={`${SHEET_CELL} ${index === 0 ? "text-foreground-secondary" : "text-muted-foreground"}`}
              >
                {row[index] ?? ""}
              </div>
            ))}
          </div>
        ))}
      </div>
    </Paper>
  );
}

/* --- data ------------------------------------------------------------------ */

const DATA_MAX_BARS = 14;
const METRIC_BOX = "min-w-0 flex-1 basis-0 rounded-[5px] border border-border px-[6px] pb-[3px] pt-[2px]";
const PLACEHOLDER_BARS = [0.34, 0.52, 0.44, 0.7, 0.58, 0.86, 0.66];

/** At most `limit` values, taken evenly across the series. */
function thin(values: number[], limit: number): number[] {
  if (values.length <= limit) return values;
  return Array.from({ length: limit }, (_, index) => values[Math.round((index * (values.length - 1)) / (limit - 1))]);
}

function barHeight(value: number): string {
  return `${Math.max(5, Math.round(value * 100))}%`;
}

function LineChart({ values }: { values: number[] }) {
  const step = values.length > 1 ? 100 / (values.length - 1) : 100;
  const points = values.map((value, index) => `${(index * step).toFixed(2)},${(38 - value * 34).toFixed(2)}`);
  if (points.length === 1) points.push(`100,${(38 - values[0] * 34).toFixed(2)}`);
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-full w-full overflow-visible" data-node-chart="line">
      <polygon points={`0,40 ${points.join(" ")} 100,40`} style={{ fill: HUE, opacity: 0.14 }} />
      <polyline
        points={points.join(" ")}
        fill="none"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        style={{ stroke: HUE }}
      />
    </svg>
  );
}

export function DataMini({ preview }: { preview: DataPreview | null }) {
  const metrics = arr(preview?.metrics)
    .map((metric) => ({ label: str(metric?.label), value: str(metric?.value) }))
    .filter((metric) => metric.label !== "" || metric.value !== "")
    .slice(0, 3);
  const series = thin(
    arr(preview?.bars).map((value) => Math.min(1, Math.max(0, num(value)))),
    DATA_MAX_BARS,
  );
  const empty = series.length === 0;
  const bars = empty ? PLACEHOLDER_BARS : series;
  const line = preview?.chart === "line" && !empty;
  return (
    <Paper>
      <div data-node-mini="data" className="flex h-full flex-col gap-[8px] px-[7%] pb-[9px] pt-[7%]">
        {metrics.length > 0 ? (
          <div className="flex shrink-0 gap-[5px]">
            {metrics.map((metric, index) => (
              <div
                key={index}
                className={
                  // A narrow card has room for two boxes, not three.
                  index === 2 ? `${METRIC_BOX} [@container(max-width:340px)]:hidden` : METRIC_BOX
                }
              >
                <p className="truncate text-[10px] leading-[13px] text-muted-foreground">{metric.label}</p>
                <p className="truncate text-[12px] font-semibold leading-[15px] tabular-nums text-foreground-strong">
                  {metric.value}
                </p>
              </div>
            ))}
          </div>
        ) : (
          empty && (
            <div className="grid shrink-0 grid-cols-2 gap-[5px]">
              {[0, 1].map((index) => (
                <div key={index} className="flex flex-col gap-[5px] rounded-[5px] border border-border px-[6px] py-[6px]">
                  <span className="h-[4px] w-[55%] rounded-full bg-foreground/[0.08]" />
                  <span className="h-[6px] w-[38%] rounded-full bg-foreground/[0.14]" />
                </div>
              ))}
            </div>
          )
        )}
        <div className="min-h-0 flex-1 border-b border-border">
          {line ? (
            <LineChart values={bars} />
          ) : (
            <div className="flex h-full items-end gap-[3px]" data-node-chart="bar">
              {bars.map((value, index) => (
                <span
                  key={index}
                  className={empty ? "min-w-0 flex-1 rounded-t-[2px] bg-foreground/[0.09]" : "min-w-0 flex-1 rounded-t-[2px]"}
                  style={
                    empty
                      ? { height: barHeight(value) }
                      : { height: barHeight(value), backgroundColor: HUE, opacity: 0.78 }
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </Paper>
  );
}

/* --- slides and motion: a stage of its own --------------------------------- */

/** A dark slide or frame keeps its own ground, whatever the app wears. */
const STAGE_DARK: CSSProperties = {
  backgroundColor: "hsl(var(--node-stage-dark))",
  color: "hsl(var(--node-stage-dark-ink))",
};

/** The title on a stage: large for a miniature, scaled with the card. */
const STAGE_TITLE =
  "line-clamp-2 font-display text-[clamp(12px,4.9cqw,23px)] leading-[1.14] [overflow-wrap:anywhere]";
const STAGE_SUBTITLE = "truncate text-[clamp(10px,2.5cqw,12px)] leading-[1.35] opacity-65";

export function SlidesMini({ preview }: { preview: SlidesPreview | null }) {
  const title = str(preview?.title).trim();
  const subtitle = str(preview?.subtitle).trim();
  const count = Math.round(num(preview?.count));
  const accent = str(preview?.accent).trim();
  return (
    <>
      <Artboard ratio={16 / 9} style={preview?.dark === true ? STAGE_DARK : undefined}>
        <div data-node-mini="slides" className="flex h-full flex-col justify-center px-[9%]">
          <span
            className="mb-[5%] block h-[3px] w-[13%] shrink-0 rounded-full"
            style={{ backgroundColor: accent !== "" ? accent : HUE }}
          />
          {title !== "" ? (
            <p className={STAGE_TITLE}>{title}</p>
          ) : (
            <span className="block h-[8px] w-[62%] rounded-full bg-current opacity-[0.16]" />
          )}
          {subtitle !== "" ? (
            <p className={`mt-[3.5%] ${STAGE_SUBTITLE}`}>{subtitle}</p>
          ) : (
            title === "" && <span className="mt-[5%] block h-[5px] w-[40%] rounded-full bg-current opacity-[0.1]" />
          )}
        </div>
      </Artboard>
      {count > 0 && <CoverPill testId="node-cover-count">{count}</CoverPill>}
    </>
  );
}

/** Seconds as a running time: 24 → "0:24", 95 → "1:35". */
export function runningTime(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

const MOTION_RATIO: Record<MotionPreview["format"], number> = {
  wide: 16 / 9,
  square: 1,
  tall: 9 / 16,
};

export function MotionMini({ preview }: { preview: MotionPreview | null }) {
  const title = str(preview?.title).trim();
  const subtitle = str(preview?.subtitle).trim();
  const seconds = num(preview?.seconds);
  const accent = str(preview?.accent).trim();
  const format = preview?.format === "square" || preview?.format === "tall" ? preview.format : "wide";
  // A film is dark unless its spec says otherwise.
  const dark = preview?.dark !== false;
  return (
    <>
      <Artboard ratio={MOTION_RATIO[format]} style={dark ? STAGE_DARK : undefined}>
        <div data-node-mini="motion" className="flex h-full flex-col justify-between px-[8%] pb-[6%] pt-[8%]">
          <div className="min-h-0">
            {title !== "" && (
              <p className={format === "wide" ? STAGE_TITLE : "line-clamp-3 font-display text-[12px] leading-[1.14] [overflow-wrap:anywhere]"}>
                {title}
              </p>
            )}
            {subtitle !== "" && format === "wide" && <p className={`mt-[3%] ${STAGE_SUBTITLE}`}>{subtitle}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-[6px]">
            {/* The play mark: a disc in the frame's ink, the triangle cut out of it. */}
            <svg viewBox="0 0 16 16" className="h-[16px] w-[16px] shrink-0" data-node-play="">
              <path
                fill="currentColor"
                fillRule="evenodd"
                d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM6.4 4.9v6.2a.4.4 0 0 0 .6.35l5.1-3.1a.4.4 0 0 0 0-.7L7 4.55a.4.4 0 0 0-.6.35Z"
              />
            </svg>
            <span className="relative block h-[2px] min-w-0 flex-1 overflow-hidden rounded-full">
              <span className="absolute inset-0 bg-current opacity-20" />
              <span
                className="absolute inset-y-0 left-0 w-[36%] rounded-full"
                style={{ backgroundColor: accent !== "" ? accent : HUE }}
              />
            </span>
          </div>
        </div>
      </Artboard>
      {seconds > 0 && <CoverPill testId="node-cover-duration">{runningTime(seconds)}</CoverPill>}
    </>
  );
}

/* --- whiteboard ------------------------------------------------------------ */

const NOTE_COLORS: readonly WhiteboardColor[] = ["yellow", "pink", "blue", "green", "violet", "orange", "gray"];

/** Where up to four notes lie on the board, a little askew. */
const NOTE_SPOTS: CSSProperties[] = [
  { left: "7%", top: "9%", transform: "rotate(-2deg)" },
  { left: "54%", top: "6%", transform: "rotate(1.5deg)" },
  { left: "11%", top: "54%", transform: "rotate(1.2deg)" },
  { left: "56%", top: "51%", transform: "rotate(-1.6deg)" },
];

/** The board's dotted grid, kept clear of the paper's edge. */
const DOT_GRID: CSSProperties = {
  backgroundImage: "radial-gradient(hsl(var(--foreground) / 0.17) 0.8px, transparent 1.1px)",
  backgroundSize: "11px 11px",
  backgroundPosition: "center top",
};

export function WhiteboardMini({ preview }: { preview: WhiteboardPreview | null }) {
  const notes = arr(preview?.notes).slice(0, NOTE_SPOTS.length);
  return (
    <Paper>
      <span className="absolute inset-x-[7px] bottom-0 top-[7px]" style={DOT_GRID} />
      <div data-node-mini="whiteboard" className="absolute inset-0">
        {notes.map((note, index) => {
          const color = NOTE_COLORS.includes(note?.color) ? note.color : "yellow";
          return (
            <div
              key={index}
              data-node-note={color}
              className="absolute h-[40%] w-[38%] overflow-hidden rounded-[3px] px-[5px] py-[4px] shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.16)]"
              style={{
                ...NOTE_SPOTS[index],
                backgroundColor: `hsl(var(--node-note-${color}))`,
                color: "hsl(var(--node-note-ink))",
              }}
            >
              <p className={`line-clamp-3 leading-[1.2] [overflow-wrap:anywhere] ${MINI_TEXT}`}>{str(note?.text)}</p>
            </div>
          );
        })}
      </div>
    </Paper>
  );
}

/* --- output: a run that left no page --------------------------------------- */

/** No more of an answer than a cover can show. */
const OUTPUT_MAX_CHARS = 640;

export function OutputMini({ preview }: { preview: OutputPreview | null }) {
  const text = str(preview?.text).trim().slice(0, OUTPUT_MAX_CHARS);
  return (
    <Paper>
      <div data-node-mini="output" className="px-[10%] pt-[9%]">
        {text !== "" ? (
          <p
            className={`line-clamp-[9] whitespace-pre-line leading-[1.4] text-muted-foreground [overflow-wrap:anywhere] ${MINI_TEXT}`}
          >
            {text}
          </p>
        ) : (
          <TextBars />
        )}
      </div>
    </Paper>
  );
}

/** A paper with nothing known about it yet: quiet bars. */
export function PlaceholderMini() {
  return (
    <Paper>
      <div data-node-mini="placeholder" className="px-[10%] pt-[10%]">
        <TextBars />
      </div>
    </Paper>
  );
}
