/**
 * The motion inside an Analytics card while an agent builds it: a figure
 * counts from its old value to its new one, columns and bars grow from their
 * baseline, a line is drawn from left to right, and a changed chart morphs
 * from its old shape to the new one.
 *
 * Nothing here changes React's DOM for good. Figures are counted through the
 * input's value and put back; charts move through Web Animations on their
 * marks. A `Run` holds everything one batch started, so the person's hands
 * (and the next batch) can finish it at once. With reduced motion nothing
 * moves.
 */
import { LIVE_TIMING } from "../playback";

/**
 * A figure such as "$1,240", "98.5%", "48,2k €" or "1.204", cut into what
 * counts and what stays. Both ways of writing numbers are read: the mark
 * that splits off the decimals is "." or ",", and the other one groups the
 * thousands. A single mark followed by exactly three digits groups ("1,240",
 * "1.204"); otherwise it splits off the decimals ("48,2", "0.125").
 */
export interface Figure {
  prefix: string;
  value: number;
  suffix: string;
  decimals: number;
  grouped: boolean;
  /** The mark that groups thousands ("," or "."), when the figure groups. */
  group: "," | ".";
  /** The mark before the decimals. */
  decimal: "." | ",";
  /** Written with a "+" in front. */
  plus: boolean;
}

const FIGURE = /^([^\d+-]*?)([+-]?\d(?:[\d.,]*\d)?)(.*)$/;

/** Which mark splits off the decimals in `digits` (sign removed), or null for a whole number. */
function decimalMark(digits: string): "." | "," | null {
  const dots = digits.split(".").length - 1;
  const commas = digits.split(",").length - 1;
  if (dots === 0 && commas === 0) return null;
  if (dots > 0 && commas > 0) return digits.lastIndexOf(".") > digits.lastIndexOf(",") ? "." : ",";
  const mark = dots > 0 ? "." : ",";
  if (dots + commas > 1) return null;
  const [whole, rest] = digits.split(mark);
  // "1,240" and "1.204" group thousands; "48,2", "98.5" and "0.125" have decimals.
  return rest.length === 3 && whole.length <= 3 && !/^0+$/.test(whole) ? null : mark;
}

export function parseFigure(text: string): Figure | null {
  const match = FIGURE.exec(text.trim());
  if (!match) return null;
  const token = match[2];
  const sign = token[0] === "-" || token[0] === "+" ? token[0] : "";
  const digits = sign ? token.slice(1) : token;
  const decimal = decimalMark(digits);
  const group: "," | "." = decimal === "," ? "." : decimal === "." ? "," : digits.includes(".") ? "." : ",";
  const [whole, fraction = ""] = decimal ? [digits.slice(0, digits.lastIndexOf(decimal)), digits.slice(digits.lastIndexOf(decimal) + 1)] : [digits, ""];
  if (/[.,]/.test(fraction) || (whole.includes(group === "," ? "." : ",") && decimal === null)) return null;
  const value = Number(`${sign === "-" ? "-" : ""}${whole.split(group).join("")}${fraction ? `.${fraction}` : ""}`);
  if (!Number.isFinite(value)) return null;
  return {
    prefix: match[1],
    value,
    suffix: match[3],
    decimals: fraction.length,
    grouped: whole.includes(group),
    group,
    decimal: decimal ?? (group === "," ? "." : ","),
    plus: sign === "+",
  };
}

/** `value` written the way `like` writes its figure. */
export function formatFigure(value: number, like: Figure, decimals = like.decimals): string {
  const fixed = Math.abs(value).toFixed(decimals);
  const [whole, fraction] = fixed.split(".");
  const body = like.grouped ? whole.replace(/\B(?=(\d{3})+(?!\d))/g, like.group) : whole;
  const sign = value < 0 ? "-" : like.plus && value > 0 ? "+" : "";
  return `${like.prefix}${sign}${body}${fraction ? `${like.decimal}${fraction}` : ""}${like.suffix}`;
}

/**
 * The figure's text at `progress` (0..1) of its count from `from` (null: from
 * zero) to `to`; null when it cannot count (not a number, or the unit changed).
 */
export function countText(from: string | null, to: string, progress: number): string | null {
  const end = parseFigure(to);
  if (!end) return null;
  const start = from === null ? null : parseFigure(from);
  let origin: number;
  if (from === null) origin = 0;
  else if (start && start.prefix === end.prefix && start.suffix === end.suffix) origin = start.value;
  else return null;
  if (progress >= 1) return to;
  const decimals = Math.max(end.decimals, start?.decimals ?? 0);
  const eased = 1 - Math.pow(1 - Math.max(0, progress), 3);
  return formatFigure(origin + (end.value - origin) * eased, end, decimals);
}

/** How long a count or draw may take when it starts `delay` ms into a batch. */
export function motionSpan(delay: number, timing = LIVE_TIMING): number {
  return Math.max(timing.fadeMs, Math.min(800, timing.maxBatchMs - delay));
}

/** Everything one batch started; finished at once by `finish`. */
export class Run {
  private timers: number[] = [];
  private frames = new Set<number>();
  private animations: Animation[] = [];
  private ends: (() => void)[] = [];
  private done = false;

  get finished(): boolean {
    return this.done;
  }

  after(ms: number, task: () => void): void {
    if (this.done) return;
    this.timers.push(window.setTimeout(task, ms));
  }

  /** `task` on the next frames until it returns true, at most `ms`. */
  until(ms: number, task: () => boolean): void {
    if (this.done) return;
    const stop = performance.now() + ms;
    const step = () => {
      if (this.done) return;
      if (task() || performance.now() >= stop) return;
      const id = window.requestAnimationFrame(() => {
        this.frames.delete(id);
        step();
      });
      this.frames.add(id);
    };
    step();
  }

  animate(el: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions): void {
    if (this.done || typeof (el as { animate?: unknown }).animate !== "function") return;
    try {
      this.animations.push(el.animate(keyframes, options));
    } catch {
      // A property the browser cannot animate stays as it is drawn.
    }
  }

  /** `task` once, `ms` from now or when the run is finished, whichever comes first. */
  atEnd(ms: number, task: () => void): void {
    if (this.done) return;
    let ran = false;
    const once = () => {
      if (ran) return;
      ran = true;
      task();
    };
    this.ends.push(once);
    this.after(ms, once);
  }

  /** `draw(progress)` over `ms`; `restore` runs when it ends or is finished early. */
  tween(ms: number, draw: (progress: number) => void, restore: () => void): void {
    if (this.done) return;
    this.ends.push(restore);
    const start = performance.now();
    this.until(ms + 60, () => {
      const progress = Math.min(1, (performance.now() - start) / ms);
      draw(progress);
      return progress >= 1;
    });
  }

  finish(): void {
    if (this.done) return;
    this.done = true;
    for (const timer of this.timers) window.clearTimeout(timer);
    for (const frame of this.frames) window.cancelAnimationFrame(frame);
    for (const animation of this.animations) animation.cancel();
    for (const end of this.ends) end();
    this.timers = [];
    this.frames.clear();
    this.animations = [];
    this.ends = [];
  }
}

/* ------------------------------------------------------------- the figures */

/** Count the figure shown in `input` from `from` (null: from zero) to what it shows now. */
export function countFigure(run: Run, input: HTMLInputElement, from: string | null, span: number): void {
  const target = input.value;
  if (countText(from, target, 0) === null) return;
  run.tween(
    span,
    (progress) => {
      if (!input.isConnected) return;
      const text = countText(from, target, progress);
      if (text !== null) input.value = text;
    },
    () => {
      if (input.isConnected && input.value !== target) input.value = target;
    },
  );
}

/* --------------------------------------------------------------- the charts */

/** What the last batch left drawn for one chart: the curves it can morph from. */
export interface ChartShape {
  signature: string;
  curves: string[];
}

const BARS = ".recharts-bar-rectangle path, .recharts-bar-rectangle rect";
const CURVES = ".recharts-line-curve, .recharts-area-curve";
const AREAS = ".recharts-area-area";
const SLICES = ".recharts-pie-sector path";

function pathLength(el: Element): number {
  const path = el as Partial<SVGGeometryElement>;
  return typeof path.getTotalLength === "function" ? path.getTotalLength() : 0;
}

/** The structure of a path's commands: two paths with the same one can morph into each other. */
function skeleton(d: string): string {
  return d.replace(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi, "#");
}

export function chartShape(svg: Element, signature: string): ChartShape {
  return { signature, curves: [...svg.querySelectorAll(CURVES)].map((el) => el.getAttribute("d") ?? "") };
}

/** How a chart is named for "same chart, new data": its type, series and points. */
export function chartSignature(chart: { type?: unknown; x?: unknown; series?: unknown } | undefined): string {
  if (!chart) return "";
  const x = Array.isArray(chart.x) ? chart.x.length : 0;
  const series = Array.isArray(chart.series) ? chart.series.length : 0;
  return `${String(chart.type)}:${series}:${x}`;
}

export interface ChartPlan {
  /** The data before (null for a chart that is new), for the bars' ratios. */
  before: { values: (number | null)[][]; signature: string } | null;
  now: { values: (number | null)[][]; signature: string };
  /** What the chart drew last time, for morphing its curves. */
  shape: ChartShape | null;
  type: string;
}

/**
 * Move the marks of the chart drawn in `piece`. The chart's SVG comes after
 * the editor's first layout, so this waits for it a short while.
 */
export function moveChart(run: Run, piece: Element, plan: ChartPlan, span: number, onShape: (shape: ChartShape) => void): void {
  let started = false;
  run.until(900, () => {
    if (started) return true;
    const svg = piece.querySelector("svg.recharts-surface");
    if (!svg || !svg.querySelector(`${BARS}, ${CURVES}, ${AREAS}, ${SLICES}`)) return false;
    started = true;
    const morph = plan.before !== null && plan.before.signature === plan.now.signature;
    const options = { duration: span, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" } as const;

    const horizontal = plan.type === "bar";
    const perSeries = plan.now.values[0]?.length || 1;
    [...svg.querySelectorAll(BARS)].forEach((bar, i) => {
      const series = Math.floor(i / perSeries);
      const point = i % perSeries;
      const old = morph ? plan.before!.values[series]?.[point] : null;
      const next = plan.now.values[series]?.[point];
      const from = typeof old === "number" && typeof next === "number" && next !== 0 ? Math.min(4, Math.max(0, old / next)) : 0;
      if (from === 1) return;
      const style = (bar as SVGElement).style;
      style.transformBox = "fill-box";
      style.transformOrigin = horizontal ? "left center" : "center bottom";
      const scale = (k: number) => (horizontal ? `scaleX(${k})` : `scaleY(${k})`);
      const lag = Math.min(point * 30, span / 2);
      run.animate(bar, [{ transform: scale(from) }, { transform: scale(1) }], { ...options, delay: lag, duration: Math.max(120, span - lag) });
    });

    [...svg.querySelectorAll(CURVES)].forEach((curve, i) => {
      const old = morph ? plan.shape?.curves[i] : undefined;
      const now = curve.getAttribute("d") ?? "";
      if (old && old !== now && skeleton(old) === skeleton(now)) {
        run.animate(curve, [{ d: `path("${old}")` } as Keyframe, { d: `path("${now}")` } as Keyframe], options);
        return;
      }
      if (old === now && morph) return;
      const length = pathLength(curve);
      if (length > 0) {
        run.animate(
          curve,
          [
            { strokeDasharray: `${length}`, strokeDashoffset: length },
            { strokeDasharray: `${length}`, strokeDashoffset: 0 },
          ],
          options,
        );
      }
    });
    // The fill under an area is wiped in from the left, as its line is drawn.
    if (!morph) {
      for (const area of svg.querySelectorAll(AREAS)) {
        run.animate(area, [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }], options);
      }
      svg.querySelectorAll(SLICES).forEach((slice, i) => {
        run.animate(slice, [{ opacity: 0 }, { opacity: 1 }], { ...options, delay: Math.min(i * 60, span / 2) });
      });
    }
    // Once at rest, remember the curves to morph from next time.
    run.atEnd(span + 80, () => onShape(chartShape(svg, plan.now.signature)));
    return true;
  });
}
