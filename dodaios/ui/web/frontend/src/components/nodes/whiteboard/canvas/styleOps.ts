/**
 * Changing how the selected things look, from the board's own inspector.
 *
 * Each change is one step the person can undo: the elements are copied with
 * a raised version (`newElementWith`) and handed to the editor with
 * `CaptureUpdateAction.IMMEDIATELY`. A box's label follows the box for its
 * colour and its type; a text whose size or font changes is measured again,
 * and a box grows when its label no longer fits.
 *
 * Commands the editor already has (duplicate, delete, layers, group, lock,
 * undo) are sent to it as its own keyboard shortcuts (`sendEditorKey`), so
 * they behave exactly as from the keyboard, bindings and history included.
 */
import { CaptureUpdateAction, newElementWith, restoreElements } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";

/** An element as this module reads it: the editor's, loosely typed. */
export type AnyElement = {
  id: string;
  type: string;
  isDeleted?: boolean;
  containerId?: string | null;
  boundElements?: readonly { id: string; type: string }[] | null;
  height: number;
  width: number;
  [key: string]: unknown;
};

/** What the inspector can change. */
export interface StylePatch {
  strokeColor?: string;
  backgroundColor?: string;
  fillStyle?: string;
  strokeWidth?: number;
  strokeStyle?: string;
  roughness?: number;
  opacity?: number;
  roundness?: { type: number } | null;
  fontSize?: number;
  fontFamily?: number;
  textAlign?: string;
  startArrowhead?: string | null;
  endArrowhead?: string | null;
}

const TEXT_KEYS = new Set(["fontSize", "fontFamily", "textAlign"]);
const SHAPES = new Set(["rectangle", "ellipse", "diamond"]);
const LINEAR = new Set(["arrow", "line"]);
/** The editor's padding between a box and its label. */
const LABEL_PADDING = 5;

/** Which keys of a patch an element of this type takes. */
export function keysFor(type: string): Set<keyof StylePatch> {
  const common: (keyof StylePatch)[] = ["opacity"];
  if (type === "text") return new Set([...common, "strokeColor", "fontSize", "fontFamily", "textAlign"]);
  if (type === "image") return new Set(common);
  if (type === "frame" || type === "magicframe") return new Set();
  if (type === "freedraw") return new Set([...common, "strokeColor", "backgroundColor", "strokeWidth"]);
  if (LINEAR.has(type)) {
    const keys: (keyof StylePatch)[] = [...common, "strokeColor", "strokeWidth", "strokeStyle", "roughness", "roundness"];
    if (type === "arrow") keys.push("startArrowhead", "endArrowhead");
    if (type === "line") keys.push("backgroundColor", "fillStyle");
    return new Set(keys);
  }
  if (SHAPES.has(type)) {
    return new Set([
      ...common,
      "strokeColor",
      "backgroundColor",
      "fillStyle",
      "strokeWidth",
      "strokeStyle",
      "roughness",
      ...(type === "ellipse" ? [] : (["roundness"] as const)),
    ]);
  }
  return new Set(common);
}

/** The selected elements, live ones only. */
export function selectedElements(editor: ExcalidrawImperativeAPI): AnyElement[] {
  const ids = editor.getAppState().selectedElementIds;
  return (editor.getSceneElements() as unknown as AnyElement[]).filter((element) => ids[element.id]);
}

/** The labels inside the given boxes. */
export function labelsOf(elements: readonly AnyElement[], all: readonly AnyElement[]): AnyElement[] {
  const wanted = new Set<string>();
  for (const element of elements) {
    for (const bound of element.boundElements ?? []) if (bound.type === "text") wanted.add(bound.id);
  }
  return all.filter((element) => wanted.has(element.id) && !element.isDeleted);
}

/** The appState key the editor keeps the default of a style under. */
const CURRENT_ITEM: Partial<Record<keyof StylePatch, string>> = {
  strokeColor: "currentItemStrokeColor",
  backgroundColor: "currentItemBackgroundColor",
  fillStyle: "currentItemFillStyle",
  strokeWidth: "currentItemStrokeWidth",
  strokeStyle: "currentItemStrokeStyle",
  roughness: "currentItemRoughness",
  opacity: "currentItemOpacity",
  fontSize: "currentItemFontSize",
  fontFamily: "currentItemFontFamily",
  textAlign: "currentItemTextAlign",
  startArrowhead: "currentItemStartArrowhead",
  endArrowhead: "currentItemEndArrowhead",
};

/** The defaults the next drawn thing takes, as the editor's appState. */
export function currentItemState(patch: StylePatch): Record<string, unknown> {
  const state: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(patch) as [keyof StylePatch, unknown][]) {
    if (key === "roundness") state.currentItemRoundness = value ? "round" : "sharp";
    else if (CURRENT_ITEM[key]) state[CURRENT_ITEM[key] as string] = value;
  }
  return state;
}

/**
 * Apply `patch` to the selection (and make it the default for what is drawn
 * next). Returns how many elements changed.
 */
export function applyStyle(editor: ExcalidrawImperativeAPI, patch: StylePatch): number {
  const all = editor.getSceneElementsIncludingDeleted() as unknown as AnyElement[];
  const selected = selectedElements(editor);
  const labels = labelsOf(selected, all);
  const changed = new Map<string, AnyElement>();
  const textChanged = new Set<string>();
  for (const element of [...selected, ...labels]) {
    const isLabel = !selected.includes(element);
    const keys = keysFor(element.type);
    const update: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(patch) as [keyof StylePatch, unknown][]) {
      if (!keys.has(key)) continue;
      // A label takes its box's colour and type, never its fill or opacity.
      if (isLabel && !(key === "strokeColor" || TEXT_KEYS.has(key))) continue;
      if (element[key] === value) continue;
      update[key] = value;
    }
    if (Object.keys(update).length === 0) continue;
    if (Object.keys(update).some((key) => TEXT_KEYS.has(key))) textChanged.add(element.id);
    changed.set(element.id, newElementWith(element as never, update as never) as unknown as AnyElement);
  }
  // Text props on a box with a label: the label is what changes.
  editor.updateScene({ appState: currentItemState(patch) as never });
  if (changed.size === 0) return 0;

  let next = all.map((element) => changed.get(element.id) ?? element);
  if (textChanged.size > 0) next = remeasure(next, textChanged, changed);
  editor.updateScene({ elements: next as never, captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  return changed.size;
}

/** Measure changed texts again and let a box grow to hold its label. */
function remeasure(
  elements: AnyElement[],
  texts: ReadonlySet<string>,
  changed: Map<string, AnyElement>,
): AnyElement[] {
  const restored = restoreElements(elements as never, null, { refreshDimensions: true, repairBindings: true }) as unknown as AnyElement[];
  const measured = new Map(restored.filter((element) => texts.has(element.id)).map((element) => [element.id, element]));
  const grow = new Map<string, AnyElement>();
  for (const text of measured.values()) {
    const before = changed.get(text.id);
    // The measured copy keeps the raised version of the change.
    if (before) Object.assign(text, { version: before.version, versionNonce: before.versionNonce });
    const containerId = text.containerId;
    if (!containerId) continue;
    const container = elements.find((element) => element.id === containerId);
    if (!container) continue;
    const factor = container.type === "ellipse" ? Math.SQRT2 : container.type === "diamond" ? 2 : 1;
    const need = (text.height + LABEL_PADDING * 2) * factor;
    if (need > container.height + 0.5) {
      grow.set(container.id, newElementWith(container as never, { height: Math.ceil(need) } as never) as unknown as AnyElement);
    }
  }
  return elements.map((element) => measured.get(element.id) ?? grow.get(element.id) ?? element);
}

/** The editor's keyboard shortcut for a command (sent to the editor itself). */
export type EditorCommand =
  | "undo"
  | "redo"
  | "duplicate"
  | "delete"
  | "front"
  | "back"
  | "group"
  | "ungroup"
  | "lock"
  | "edit-text"
  | "select-all";

const KEYS: Record<EditorCommand, { key: string; code: string; ctrl?: boolean; shift?: boolean; alt?: boolean }> = {
  undo: { key: "z", code: "KeyZ", ctrl: true },
  redo: { key: "z", code: "KeyZ", ctrl: true, shift: true },
  duplicate: { key: "d", code: "KeyD", ctrl: true },
  delete: { key: "Delete", code: "Delete" },
  front: { key: "]", code: "BracketRight", ctrl: true, shift: true },
  back: { key: "[", code: "BracketLeft", ctrl: true, shift: true },
  group: { key: "g", code: "KeyG", ctrl: true },
  ungroup: { key: "g", code: "KeyG", ctrl: true, shift: true },
  lock: { key: "l", code: "KeyL", ctrl: true, shift: true },
  "edit-text": { key: "Enter", code: "Enter" },
  "select-all": { key: "a", code: "KeyA", ctrl: true },
};

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "");

/**
 * Run an editor command by sending its shortcut to the editor's own element,
 * where its key handler listens.
 */
export function sendEditorKey(root: HTMLElement | null, command: EditorCommand): boolean {
  const target = root?.querySelector<HTMLElement>(".excalidraw-container") ?? root?.querySelector<HTMLElement>(".excalidraw");
  if (!target) return false;
  const spec = KEYS[command];
  const event = new KeyboardEvent("keydown", {
    key: spec.shift && spec.key.length === 1 && /[a-z]/.test(spec.key) ? spec.key.toUpperCase() : spec.key,
    code: spec.code,
    ctrlKey: Boolean(spec.ctrl) && !IS_MAC,
    metaKey: Boolean(spec.ctrl) && IS_MAC,
    shiftKey: Boolean(spec.shift),
    altKey: Boolean(spec.alt),
    bubbles: true,
    cancelable: true,
  });
  target.dispatchEvent(event);
  return true;
}
