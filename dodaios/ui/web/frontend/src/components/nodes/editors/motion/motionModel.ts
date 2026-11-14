/**
 * The clip ("motion") spec as the editor sees it, and every change the editor
 * makes to it.
 *
 * The spec's grammar lives in `dodaios/nodes/kinds/motion.py`; this module
 * mirrors the parts the editor needs so a change is right BEFORE it reaches
 * the server: which fields a scene type keeps, what it cannot do without,
 * the bounds of a scene's length, how long a scene runs by default. The
 * server's `normalize` stays the judge (a save returns the spec as it was
 * kept); the mirror only saves the person a refused save.
 *
 * Every change is a draft mutator for `useNodeSpecEditor().apply`, so each
 * one is a single undo step and the history stays cheap (structural sharing).
 * The functions are pure and React-free, so they are tested on their own.
 */
import { validateChart } from "../charts/chartModel";

/** The scene types, in the order the "Add scene" menu offers them. */
export const SCENE_KINDS = [
  "title",
  "text",
  "bullets",
  "stat",
  "bars",
  "chart",
  "steps",
  "quote",
  "image",
  "end",
] as const;
export type SceneKind = (typeof SCENE_KINDS)[number];

export const TRANSITIONS = ["fade", "slide", "zoom", "cut"] as const;
export type Transition = (typeof TRANSITIONS)[number];

export const FORMATS = ["wide", "square", "tall"] as const;
export type ClipFormat = (typeof FORMATS)[number];

export const THEMES = ["dark", "light"] as const;
export type ClipTheme = (typeof THEMES)[number];

/** The width : height of each format's stage (`FORMATS` in motion.py). */
export const FORMAT_RATIO: Record<ClipFormat, number> = { wide: 16 / 9, square: 1, tall: 9 / 16 };

export const MAX_SCENES = 40;
export const MIN_SECONDS = 1.5;
export const MAX_SECONDS = 20;
export const MAX_BULLETS = 5;
export const MAX_ITEMS = 8;
export const MAX_STEPS = 5;
/** The largest embedded picture the spec keeps (`shell.MAX_IMAGE_CHARS`). */
export const MAX_IMAGE_CHARS = 400_000;

/** The longest text each field keeps (the `shell.clean` limits in motion.py). */
export const LIMITS = {
  kicker: 60,
  title: 120,
  text: 280,
  bullet: 120,
  value: 24,
  unit: 12,
  label: 80,
  detail: 140,
  itemLabel: 40,
  quote: 320,
  by: 80,
  stepTitle: 60,
  stepText: 140,
  caption: 140,
} as const;

export interface BarItem {
  label: string;
  value: number;
}

export interface Step {
  title: string;
  text: string;
}

/** A chart in the shared chart grammar (`report_blocks.parse_chart`), kept as JSON. */
export type ChartJson = Record<string, unknown>;

export interface Scene {
  type: SceneKind;
  seconds: number;
  transition: Transition;
  kicker?: string;
  title?: string;
  text?: string;
  bullets?: string[];
  value?: string;
  unit?: string;
  label?: string;
  detail?: string;
  items?: BarItem[];
  quote?: string;
  by?: string;
  steps?: Step[];
  image?: string;
  caption?: string;
  chart?: ChartJson;
}

export type SceneField = Exclude<keyof Scene, "type" | "seconds" | "transition">;
export type TextField = "kicker" | "title" | "text" | "value" | "unit" | "label" | "detail" | "quote" | "by" | "caption";

export interface MotionSpec {
  format: ClipFormat;
  theme: ClipTheme;
  /** A colour name, a hex/rgb/hsl, or "" for the app's accent. */
  accent: string;
  loop: boolean;
  scenes: Scene[];
}

/** The fields each scene type keeps (`_FIELDS`); anything else is dropped by the server. */
export const FIELDS: Record<SceneKind, readonly SceneField[]> = {
  title: ["kicker", "title", "text"],
  text: ["kicker", "text"],
  bullets: ["kicker", "title", "bullets"],
  stat: ["kicker", "value", "unit", "label", "detail"],
  bars: ["kicker", "title", "items", "unit"],
  quote: ["quote", "by"],
  steps: ["kicker", "title", "steps"],
  image: ["image", "caption"],
  chart: ["kicker", "title", "chart"],
  end: ["kicker", "title", "text"],
};

/** What a scene type cannot do without (`_NEEDS`): the server refuses the spec otherwise. */
export const NEEDS: Record<SceneKind, SceneField> = {
  title: "title",
  text: "text",
  bullets: "bullets",
  stat: "value",
  bars: "items",
  quote: "quote",
  steps: "steps",
  image: "image",
  chart: "chart",
  end: "title",
};

// --- reading -------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : typeof value === "number" ? String(value) : "";
}

/** A scene's length kept in bounds and to one decimal, as the server stores it. */
export function clampSeconds(value: number): number {
  if (!Number.isFinite(value)) return MIN_SECONDS;
  return Math.round(Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, value)) * 10) / 10;
}

function readScene(raw: unknown): Scene | null {
  if (!isRecord(raw)) return null;
  const type = pick(raw.type, SCENE_KINDS, "text");
  const scene: Scene = {
    type,
    seconds: 0,
    transition: pick(raw.transition, TRANSITIONS, "fade"),
  };
  for (const field of FIELDS[type]) {
    const value = raw[field];
    if (field === "bullets" && Array.isArray(value)) scene.bullets = value.map(text);
    else if (field === "items" && Array.isArray(value))
      scene.items = value.filter(isRecord).map((item) => ({
        label: text(item.label),
        value: typeof item.value === "number" && Number.isFinite(item.value) ? item.value : 0,
      }));
    else if (field === "steps" && Array.isArray(value))
      scene.steps = value.filter(isRecord).map((step) => ({ title: text(step.title), text: text(step.text) }));
    else if (field === "chart" && isRecord(value)) scene.chart = value;
    else if (typeof value === "string" || typeof value === "number") (scene as unknown as Record<string, unknown>)[field] = text(value);
  }
  const seconds = typeof raw.seconds === "number" ? raw.seconds : Number.NaN;
  scene.seconds = Number.isFinite(seconds) ? clampSeconds(seconds) : defaultSeconds(scene);
  return scene;
}

/**
 * The spec in the editor's shape. The server hands over a normalized spec, so
 * this mostly passes it through; it is defensive because a spec written by an
 * older version, or a broken one, must still open in the editor.
 */
export function readMotionSpec(raw: unknown): MotionSpec {
  const spec = isRecord(raw) ? raw : {};
  const scenes = (Array.isArray(spec.scenes) ? spec.scenes : [])
    .map(readScene)
    .filter((scene): scene is Scene => scene !== null)
    .slice(0, MAX_SCENES);
  return {
    format: pick(spec.format, FORMATS, "wide"),
    theme: pick(spec.theme, THEMES, "dark"),
    accent: typeof spec.accent === "string" ? spec.accent : "",
    loop: spec.loop === true,
    scenes,
  };
}

// --- time ----------------------------------------------------------------------

/**
 * How long a scene runs when nobody chose (`_default_seconds`): its entrance
 * plus a hold, longer for more to read. "Fit to content" sets this again.
 */
export function defaultSeconds(scene: Scene): number {
  const count = (list: unknown[] | undefined) => list?.length ?? 0;
  let seconds = 4;
  if (scene.type === "bullets") seconds = Math.min(6, 3 + 0.6 * count(scene.bullets));
  else if (scene.type === "bars") seconds = Math.min(6, 3.4 + 0.3 * count(scene.items));
  else if (scene.type === "steps") seconds = Math.min(6.5, 3 + 0.8 * count(scene.steps));
  else if (scene.type === "text") seconds = Math.min(7, 3 + (scene.text ?? "").length / 45);
  else if (scene.type === "quote") seconds = Math.min(8, 3.5 + (scene.quote ?? "").length / 45);
  else if (scene.type === "image" || scene.type === "chart") seconds = 5;
  return clampSeconds(seconds);
}

/** The clip's whole length in seconds, to one decimal (`_total`). */
export function totalSeconds(spec: MotionSpec): number {
  return Math.round(spec.scenes.reduce((sum, scene) => sum + scene.seconds, 0) * 10) / 10;
}

/** When each scene starts on the clip's clock. */
export function sceneStarts(spec: MotionSpec): number[] {
  const starts: number[] = [];
  let at = 0;
  for (const scene of spec.scenes) {
    starts.push(at);
    at += scene.seconds;
  }
  return starts;
}

/** Which scene is on at `t` seconds (the page's own `index(t)`). */
export function sceneAt(spec: MotionSpec, t: number): number {
  const starts = sceneStarts(spec);
  let index = 0;
  for (let n = 1; n < starts.length; n += 1) if (starts[n] <= t) index = n;
  return index;
}

/** `m:ss`, as the page's own clock writes it; with tenths for a scene's length. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds + 1e-6));
  const rest = whole % 60;
  return `${Math.floor(whole / 60)}:${rest < 10 ? "0" : ""}${rest}`;
}

export function formatSeconds(seconds: number, language = "en"): string {
  try {
    return new Intl.NumberFormat(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(seconds);
  } catch {
    return seconds.toFixed(1);
  }
}

// --- checking ------------------------------------------------------------------

/**
 * Why the server would refuse this scene, or null. The editor marks such a
 * scene and says what it needs before the save fails with the type's sentence.
 */
export function sceneProblem(scene: Scene): SceneField | null {
  const needed = NEEDS[scene.type];
  const value = scene[needed];
  if (needed === "items") return (scene.items ?? []).length > 0 ? null : needed;
  if (needed === "bullets") return (scene.bullets ?? []).some((point) => point.trim()) ? null : needed;
  if (needed === "steps") return (scene.steps ?? []).some((step) => step.title.trim() || step.text.trim()) ? null : needed;
  // A chart scene's chart is the shared grammar: the same check the chart editor runs.
  if (needed === "chart") return validateChart(value).errors.length === 0 ? null : needed;
  return typeof value === "string" && value.trim() ? null : needed;
}

/** The first text a scene shows: what its block on the timeline is named by. */
export function sceneSummary(scene: Scene): string {
  for (const field of ["title", "text", "quote", "value", "caption", "label"] as const) {
    const value = scene[field];
    if (typeof value === "string" && value.trim()) {
      return field === "value" && scene.unit ? `${value} ${scene.unit}` : value;
    }
  }
  if (scene.type === "bullets") return (scene.bullets ?? []).find((point) => point.trim()) ?? "";
  if (scene.type === "steps") return scene.steps?.[0]?.title ?? "";
  if (scene.type === "chart" && isRecord(scene.chart) && typeof scene.chart.title === "string") return scene.chart.title;
  return "";
}

// --- making scenes -------------------------------------------------------------

/**
 * The words a new scene starts with, in the person's language. They make a new
 * scene valid at once (the server refuses an empty one) and are meant to be
 * written over.
 */
export interface SceneSamples {
  title: string;
  text: string;
  point: (n: number) => string;
  statLabel: string;
  barLabel: (n: number) => string;
  quote: string;
  by: string;
  step: (n: number) => string;
  end: string;
}

/** A small embedded picture so a new image scene is valid until a picture is chosen. */
export const PLACEHOLDER_IMAGE =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==";

/** A small trend for a new chart scene; the scene's own heading names it. */
export function sampleChart(): ChartJson {
  return {
    type: "line",
    x: ["Q1", "Q2", "Q3", "Q4"],
    series: [{ name: "", data: [12, 18, 15, 24] }],
  };
}

/** A new scene of `kind`, filled with sample words, its length fitted to them. */
export function newScene(kind: SceneKind, samples: SceneSamples): Scene {
  const scene: Scene = { type: kind, seconds: 4, transition: "fade" };
  switch (kind) {
    case "title":
      scene.title = samples.title;
      break;
    case "end":
      scene.title = samples.end;
      break;
    case "text":
      scene.text = samples.text;
      break;
    case "bullets":
      scene.title = samples.title;
      scene.bullets = [1, 2, 3].map(samples.point);
      break;
    case "stat":
      scene.value = "42";
      scene.unit = "%";
      scene.label = samples.statLabel;
      break;
    case "bars":
      scene.title = samples.title;
      scene.items = [
        { label: samples.barLabel(1), value: 40 },
        { label: samples.barLabel(2), value: 25 },
        { label: samples.barLabel(3), value: 15 },
      ];
      break;
    case "quote":
      scene.quote = samples.quote;
      scene.by = samples.by;
      break;
    case "steps":
      scene.title = samples.title;
      scene.steps = [1, 2, 3].map((n) => ({ title: samples.step(n), text: "" }));
      break;
    case "image":
      scene.image = PLACEHOLDER_IMAGE;
      break;
    case "chart":
      scene.title = samples.title;
      scene.chart = sampleChart();
      break;
  }
  scene.seconds = defaultSeconds(scene);
  return scene;
}

/**
 * The scene as another type, keeping what carries over: the heading and its
 * kicker, a statement as a quote, points as steps or bars and back. What the
 * new type needs and cannot take from the old one comes from the samples, so
 * the switch never leaves a scene the server would refuse. Length and
 * transition stay; a length the person never changed follows the new content.
 */
export function convertScene(scene: Scene, kind: SceneKind, samples: SceneSamples): Scene {
  if (scene.type === kind) return scene;
  const fresh = newScene(kind, samples);
  const words: string[] =
    scene.bullets ??
    scene.steps?.map((step) => step.title || step.text) ??
    scene.items?.map((item) => item.label) ??
    [];
  const heading = scene.title || scene.label || "";
  const statement = scene.text || scene.quote || scene.caption || scene.detail || "";
  const next: Scene = { type: kind, seconds: scene.seconds, transition: scene.transition };
  const keeps = FIELDS[kind];
  if (keeps.includes("kicker") && scene.kicker) next.kicker = scene.kicker;
  if (keeps.includes("title")) next.title = (heading || statement).slice(0, LIMITS.title) || fresh.title;
  if (keeps.includes("text") && kind === "text") next.text = (statement || heading).slice(0, LIMITS.text) || fresh.text;
  else if (keeps.includes("text") && scene.text && next.title !== scene.text) next.text = scene.text;
  if (kind === "quote") {
    next.quote = (statement || heading).slice(0, LIMITS.quote) || fresh.quote;
    next.by = scene.by ?? fresh.by;
  }
  if (kind === "bullets")
    next.bullets = words.length ? words.slice(0, MAX_BULLETS).map((w) => w.slice(0, LIMITS.bullet)) : fresh.bullets;
  if (kind === "steps")
    next.steps = words.length
      ? words.slice(0, MAX_STEPS).map((w) => ({ title: w.slice(0, LIMITS.stepTitle), text: "" }))
      : fresh.steps;
  if (kind === "bars")
    next.items = words.length
      ? words.slice(0, MAX_ITEMS).map((w, n) => ({ label: w.slice(0, LIMITS.itemLabel), value: scene.items?.[n]?.value ?? 10 * (MAX_ITEMS - n) }))
      : fresh.items;
  if (kind === "bars" && scene.unit) next.unit = scene.unit;
  if (kind === "stat") {
    next.value = scene.value || fresh.value;
    next.unit = scene.unit ?? fresh.unit;
    next.label = (scene.label || heading).slice(0, LIMITS.label) || fresh.label;
    if (scene.detail) next.detail = scene.detail;
  }
  if (kind === "image") {
    next.image = scene.image ?? fresh.image;
    if (scene.caption || statement) next.caption = (scene.caption || statement).slice(0, LIMITS.caption);
  }
  if (kind === "chart") next.chart = scene.chart ?? fresh.chart;
  if (scene.seconds === defaultSeconds(scene)) next.seconds = defaultSeconds(next);
  return next;
}

// --- changes (draft mutators for `apply`) --------------------------------------

/** Insert `scene` at `index` (clamped). Refused past `MAX_SCENES`. */
export function insertScene(draft: MotionSpec, index: number, scene: Scene): boolean {
  if (draft.scenes.length >= MAX_SCENES) return false;
  const at = Math.max(0, Math.min(draft.scenes.length, index));
  draft.scenes.splice(at, 0, scene);
  return true;
}

/** A copy of scene `index` right after it. */
export function duplicateScene(draft: MotionSpec, index: number): boolean {
  const scene = draft.scenes[index];
  if (!scene || draft.scenes.length >= MAX_SCENES) return false;
  draft.scenes.splice(index + 1, 0, plain(scene));
  return true;
}

/** Remove scene `index`; a clip keeps at least one scene. */
export function removeScene(draft: MotionSpec, index: number): boolean {
  if (draft.scenes.length <= 1 || !draft.scenes[index]) return false;
  draft.scenes.splice(index, 1);
  return true;
}

/** Move scene `from` so it ends up at index `to`. */
export function moveScene(draft: MotionSpec, from: number, to: number): boolean {
  const count = draft.scenes.length;
  if (from < 0 || from >= count) return false;
  const target = Math.max(0, Math.min(count - 1, to));
  if (target === from) return false;
  const [scene] = draft.scenes.splice(from, 1);
  draft.scenes.splice(target, 0, scene);
  return true;
}

/** Where a scene dragged from `from` and dropped before slot `slot` (0…count) lands. */
export function dropIndex(from: number, slot: number): number {
  return slot > from ? slot - 1 : slot;
}

export function setSeconds(draft: MotionSpec, index: number, seconds: number): void {
  const scene = draft.scenes[index];
  if (scene) scene.seconds = clampSeconds(seconds);
}

/** Copy the draft's plain data (a draft proxy cannot be cloned directly). */
function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// --- one value at a place (the preview's direct edits) -------------------------

/** A JSON Pointer's parts (`/scenes/0/title` → ["scenes", "0", "title"]). */
export function pointerParts(path: string): string[] | null {
  if (!path.startsWith("/")) return null;
  return path
    .slice(1)
    .split("/")
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
}

/** The value at `path`, or undefined when the spec has none there. */
export function readAtPointer(spec: unknown, path: string): unknown {
  const parts = pointerParts(path);
  if (!parts) return undefined;
  let node: unknown = spec;
  for (const part of parts) {
    if (Array.isArray(node)) node = node[Number(part)];
    else if (isRecord(node) && Object.prototype.hasOwnProperty.call(node, part)) node = node[part];
    else return undefined;
  }
  return node;
}

/**
 * Write `value` where `path` points, only where the spec already has a value
 * (the page offers exactly those places). Returns whether it was written.
 */
export function setAtPointer(draft: unknown, path: string, value: unknown): boolean {
  const parts = pointerParts(path);
  if (!parts || parts.length === 0) return false;
  let node: unknown = draft;
  for (const part of parts.slice(0, -1)) {
    if (Array.isArray(node)) node = node[Number(part)];
    else if (isRecord(node)) node = node[part];
    else return false;
  }
  const last = parts[parts.length - 1];
  if (Array.isArray(node)) {
    const index = Number(last);
    if (!Number.isInteger(index) || index < 0 || index >= node.length) return false;
    node[index] = value;
    return true;
  }
  if (isRecord(node) && last in node) {
    node[last] = value;
    return true;
  }
  return false;
}

/**
 * What a person typed as a number, in the notation people use; NaN when it is
 * not one. The same reading as the server's `edit.read_number`: "1.234,5",
 * "1,234.5", "40,62", "1 200", "€ 12" all read as the number they mean, and one
 * separator before exactly three digits is a thousands mark.
 */
export function readNumber(typed: string): number {
  let value = typed.trim().replace(/^[€$£¥%]+|[€$£¥%]+$/g, "").trim();
  if (value === "") return Number.NaN;
  if (!/^[+-]?[\d.,'   ]*\d[\d.,'   ]*$/.test(value)) return Number.NaN;
  const sign = value.startsWith("-") ? -1 : 1;
  value = value.replace(/^[+-]+/, "").replace(/['   ]/g, "");
  const marks = value.replace(/[^.,]/g, "");
  let whole = value;
  let fraction = "";
  if (marks.includes(".") && marks.includes(",")) {
    const point = value[Math.max(value.lastIndexOf("."), value.lastIndexOf(","))];
    if (value.split(point).length !== 2) return Number.NaN;
    [whole, fraction] = value.split(point === "," ? "." : ",").join("").split(point);
  } else if (marks) {
    const mark = marks[0];
    const cut = value.lastIndexOf(mark);
    const head = value.slice(0, cut);
    const tail = value.slice(cut + 1);
    if (marks.length > 1 || (tail.length === 3 && head !== "" && head !== "0")) whole = value.split(mark).join("");
    else {
      whole = head;
      fraction = tail;
    }
  }
  if (!/^\d*$/.test(whole) || !/^\d*$/.test(fraction)) return Number.NaN;
  return sign * Number.parseFloat(`${whole || "0"}.${fraction || "0"}`);
}
