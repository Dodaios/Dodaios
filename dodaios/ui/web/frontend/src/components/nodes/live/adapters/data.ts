/**
 * How an analysis (Analytics) is revealed while an agent builds it.
 *
 * It is built the way a person would build the page by hand, top to bottom:
 * the summary and sources, then each section's heading, its figures, its
 * charts and its tables, one card at a time. The frame and the name tag sit
 * on the card being written. Inside a card the motion is its own
 * (`dataMotion.ts`): a figure counts from its old value to its new one,
 * columns and bars grow from the baseline, a line is drawn left to right, and
 * a changed chart morphs. Only what changed plays; opened mid-build, everything
 * there plays once.
 *
 * Cards are marked in the editor with `data-live-path` (`/summary`,
 * `/sections/0/title`, `/sections/0/metrics/1`, `/sections/0/charts/0`, …).
 */
import { readDashSpec, type DashChart, type DashMetric, type DashSpec } from "../../editors/data/dashboardModel";
import { revealDelays, prefersReducedMotion } from "../playback";
import type { RevealAdapter, RevealInput, RevealStep } from "../reveal";
import {
  chartSignature,
  countFigure,
  moveChart,
  motionSpan,
  Run,
  type ChartPlan,
  type ChartShape,
} from "./dataMotion";

type Kind = "text" | "sources" | "metric" | "chart" | "table";

/** One card to write: where it is, what it is, and what stood there before. */
export interface DataEntry {
  path: string;
  kind: Kind;
  before?: unknown;
  now?: unknown;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * The cards of `next` that differ from `previous`, in reading order. With no
 * previous spec every card is new.
 */
export function dataEntries(previous: DashSpec | null, next: DashSpec): DataEntry[] {
  const out: DataEntry[] = [];
  if (next.summary.trim() && (!previous || previous.summary !== next.summary)) {
    out.push({ path: "/summary", kind: "text" });
  }
  if ((next.sources?.length ?? 0) > 0 && (!previous || !same(previous.sources ?? [], next.sources))) {
    out.push({ path: "/sources", kind: "sources" });
  }
  next.sections.forEach((section, s) => {
    const old = previous?.sections[s];
    if ((section.title.trim() || section.text.trim()) && (!old || old.title !== section.title || old.text !== section.text)) {
      out.push({ path: `/sections/${s}/title`, kind: "text" });
    }
    section.metrics.forEach((metric, i) => {
      const was = old?.metrics[i];
      if (!was || !same(was, metric)) out.push({ path: `/sections/${s}/metrics/${i}`, kind: "metric", before: was, now: metric });
    });
    section.charts.forEach((chart, i) => {
      const was = old?.charts[i];
      if (!was || !same(was, chart)) out.push({ path: `/sections/${s}/charts/${i}`, kind: "chart", before: was, now: chart });
    });
    section.tables.forEach((table, i) => {
      const was = old?.tables[i];
      if (!was || !same(was, table)) out.push({ path: `/sections/${s}/tables/${i}`, kind: "table" });
    });
  });
  return out;
}

/** The numbers a chart draws, one list per series. */
function valuesOf(chart: DashChart): (number | null)[][] {
  return (Array.isArray(chart.series) ? chart.series : []).map((series) =>
    (Array.isArray(series.data) ? series.data : []).map((v) => (typeof v === "number" ? v : null)),
  );
}

/** What one editor body remembers between batches. */
interface BodyState {
  run: Run | null;
  shapes: Map<string, ChartShape>;
  listening: boolean;
}

const bodies = new WeakMap<HTMLElement, BodyState>();
const PERSON_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

function stateOf(root: HTMLElement): BodyState {
  let state = bodies.get(root);
  if (!state) {
    state = { run: null, shapes: new Map(), listening: false };
    bodies.set(root, state);
  }
  if (!state.listening) {
    state.listening = true;
    // The person's hands finish the motion inside the cards, as they finish the fades.
    const stop = () => bodies.get(root)?.run?.finish();
    for (const name of PERSON_EVENTS) root.addEventListener(name, stop, { capture: true, passive: true });
  }
  return state;
}

function cardAt(root: HTMLElement, path: string): Element | null {
  return root.querySelector(`[data-live-path="${path}"]`);
}

/** Start the motion inside the cards, each as its card is revealed. */
function startMotion(state: BodyState, entries: DataEntry[], cards: Element[]): void {
  const run = new Run();
  state.run = run;
  const delays = revealDelays(cards.length);
  entries.forEach((entry, at) => {
    const card = cards[at];
    const delay = delays[at] ?? 0;
    const span = motionSpan(delay);
    if (entry.kind === "metric") {
      const now = entry.now as DashMetric;
      const was = entry.before as DashMetric | undefined;
      if (was && was.value === now.value) return;
      run.after(delay, () => {
        const input = card.querySelector<HTMLInputElement>('[data-testid="data-metric-value"]');
        if (input) countFigure(run, input, was ? was.value : null, span);
      });
    } else if (entry.kind === "chart") {
      const now = entry.now as DashChart;
      const was = entry.before as DashChart | undefined;
      const plan: ChartPlan = {
        before: was ? { values: valuesOf(was), signature: chartSignature(was) } : null,
        now: { values: valuesOf(now), signature: chartSignature(now) },
        shape: state.shapes.get(entry.path) ?? null,
        type: String(now.type),
      };
      run.after(delay, () => moveChart(run, card, plan, span, (shape) => state.shapes.set(entry.path, shape)));
    }
  });
}

export const dataReveal: RevealAdapter = {
  steps({ previous, next, root, initial }: RevealInput): RevealStep[] {
    const state = stateOf(root);
    state.run?.finish();
    state.run = null;
    const entries = dataEntries(initial || !previous ? null : readDashSpec(previous), readDashSpec(next));
    // Only cards that are drawn; the player skips a step with no card, and the motion must line up.
    const found: DataEntry[] = [];
    const cards: Element[] = [];
    for (const entry of entries) {
      const card = cardAt(root, entry.path);
      if (!card) continue;
      found.push(entry);
      cards.push(card);
    }
    if (found.length > 0 && !prefersReducedMotion()) startMotion(state, found, cards);
    return cards.map((element) => ({ target: { element } }));
  },
};
