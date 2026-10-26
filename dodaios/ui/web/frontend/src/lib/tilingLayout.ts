import type { SectionId } from "@/store/events";
import { SETTINGS_HUB_IDS } from "@/components/layout/navGroups";
import { sectionWindow } from "@/lib/sectionWindows";

/**
 * The tiling layout: several sections side by side in the main window.
 *
 * A layout is a binary tree. A leaf shows one section; a split cuts its area
 * into two parts, side by side (`row`) or one above the other (`column`), at
 * `ratio` (the share the first part gets). Every function here is pure, so the
 * store and the tests share one implementation.
 */
export type TileDir = "row" | "column";

export interface TileLeaf {
  kind: "leaf";
  id: string;
  section: SectionId;
}

export interface TileSplit {
  kind: "split";
  id: string;
  dir: TileDir;
  ratio: number;
  a: TileNode;
  b: TileNode;
}

export type TileNode = TileLeaf | TileSplit;

/** A rectangle in fractions of the stage (0..1). */
export interface TileRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const FULL_RECT: TileRect = { x: 0, y: 0, w: 1, h: 1 };

/** More tiles than this stop being readable on one monitor. */
export const MAX_TILES = 6;

export const MIN_RATIO = 0.15;
export const MAX_RATIO = 0.85;

let counter = 0;
export function tileId(prefix = "t"): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter.toString(36)}`;
}

/** Sections that open as a dialog over the stage instead of in a tile. */
export function isOverlaySection(section: string): boolean {
  return (
    section === "plugins" || section === "mcps" || section === "skills" ||
    (SETTINGS_HUB_IDS as readonly string[]).includes(section)
  );
}

export function isTileable(section: SectionId): boolean {
  return !isOverlaySection(section);
}

export function leaf(section: SectionId): TileLeaf {
  return { kind: "leaf", id: tileId("l"), section };
}

export function split(dir: TileDir, a: TileNode, b: TileNode, ratio = 0.5): TileSplit {
  return { kind: "split", id: tileId("s"), dir, ratio, a, b };
}

export function leaves(node: TileNode | null): TileLeaf[] {
  if (!node) return [];
  return node.kind === "leaf" ? [node] : [...leaves(node.a), ...leaves(node.b)];
}

export function findLeaf(node: TileNode | null, id: string | null): TileLeaf | undefined {
  return id ? leaves(node).find((item) => item.id === id) : undefined;
}

/** The leaf showing `section`'s window family (tabs of one hub share a tile). */
export function leafForSection(node: TileNode | null, section: SectionId): TileLeaf | undefined {
  const owner = sectionWindow(section);
  return leaves(node).find((item) => sectionWindow(item.section) === owner);
}

function cut(rect: TileRect, dir: TileDir, ratio: number): [TileRect, TileRect] {
  if (dir === "row") {
    const w = rect.w * ratio;
    return [{ ...rect, w }, { ...rect, x: rect.x + w, w: rect.w - w }];
  }
  const h = rect.h * ratio;
  return [{ ...rect, h }, { ...rect, y: rect.y + h, h: rect.h - h }];
}

export function layoutLeaves(
  node: TileNode | null,
  rect: TileRect = FULL_RECT,
): { leaf: TileLeaf; rect: TileRect }[] {
  if (!node) return [];
  if (node.kind === "leaf") return [{ leaf: node, rect }];
  const [ra, rb] = cut(rect, node.dir, node.ratio);
  return [...layoutLeaves(node.a, ra), ...layoutLeaves(node.b, rb)];
}

export function layoutSplits(
  node: TileNode | null,
  rect: TileRect = FULL_RECT,
): { split: TileSplit; rect: TileRect }[] {
  if (!node || node.kind === "leaf") return [];
  const [ra, rb] = cut(rect, node.dir, node.ratio);
  return [{ split: node, rect }, ...layoutSplits(node.a, ra), ...layoutSplits(node.b, rb)];
}

function mapNode(node: TileNode, fn: (item: TileNode) => TileNode | null): TileNode | null {
  const own = fn(node);
  if (own !== node) return own;
  if (node.kind === "leaf") return node;
  const a = mapNode(node.a, fn);
  const b = mapNode(node.b, fn);
  if (a === node.a && b === node.b) return node;
  if (!a) return b;
  if (!b) return a;
  return { ...node, a, b };
}

/** Replace the leaf `id` with a split holding it and a new leaf for `section`. */
export function splitLeaf(
  tree: TileNode,
  id: string,
  section: SectionId,
  dir: TileDir,
  placeAfter = true,
): { tree: TileNode; added: TileLeaf } {
  const added = leaf(section);
  const next = mapNode(tree, (item) => {
    if (item.kind !== "leaf" || item.id !== id) return item;
    return placeAfter ? split(dir, item, added) : split(dir, added, item);
  });
  return { tree: next ?? tree, added };
}

/** Remove a leaf; its sibling takes the parent's place. Null when it was the last. */
export function removeLeaf(tree: TileNode, id: string): TileNode | null {
  return mapNode(tree, (item) => (item.kind === "leaf" && item.id === id ? null : item));
}

export function setLeafSection(tree: TileNode, id: string, section: SectionId): TileNode {
  return mapNode(tree, (item) =>
    item.kind === "leaf" && item.id === id && item.section !== section ? { ...item, section } : item,
  ) ?? tree;
}

export function clampRatio(ratio: number): number {
  if (!Number.isFinite(ratio)) return 0.5;
  return Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio));
}

export function setRatio(tree: TileNode, id: string, ratio: number): TileNode {
  const clamped = clampRatio(ratio);
  return mapNode(tree, (item) =>
    item.kind === "split" && item.id === id && item.ratio !== clamped ? { ...item, ratio: clamped } : item,
  ) ?? tree;
}

/** Exchange the sections of two leaves; the tiles keep their places. */
export function swapLeaves(tree: TileNode, first: string, second: string): TileNode {
  const a = findLeaf(tree, first);
  const b = findLeaf(tree, second);
  if (!a || !b || a.id === b.id) return tree;
  return mapNode(tree, (item) => {
    if (item.kind !== "leaf") return item;
    if (item.id === a.id) return { ...item, section: b.section };
    if (item.id === b.id) return { ...item, section: a.section };
    return item;
  }) ?? tree;
}

/** Split direction that keeps the new tiles closest to square (dwindle). */
export function dwindleDir(rect: TileRect, stageAspect: number): TileDir {
  return rect.w * stageAspect >= rect.h ? "row" : "column";
}

export type PresetId = "single" | "columns-2" | "rows-2" | "main-stack" | "stack-main" | "columns-3" | "grid-4";

export interface TilePreset {
  id: PresetId;
  slots: number;
  build: (sections: SectionId[]) => TileNode;
}

export const PRESETS: readonly TilePreset[] = [
  { id: "single", slots: 1, build: ([a]) => leaf(a) },
  { id: "columns-2", slots: 2, build: ([a, b]) => split("row", leaf(a), leaf(b)) },
  { id: "rows-2", slots: 2, build: ([a, b]) => split("column", leaf(a), leaf(b)) },
  {
    id: "main-stack",
    slots: 3,
    build: ([a, b, c]) => split("row", leaf(a), split("column", leaf(b), leaf(c))),
  },
  {
    id: "stack-main",
    slots: 3,
    build: ([a, b, c]) => split("row", split("column", leaf(a), leaf(b)), leaf(c)),
  },
  {
    id: "columns-3",
    slots: 3,
    build: ([a, b, c]) => split("row", leaf(a), split("row", leaf(b), leaf(c)), 1 / 3),
  },
  {
    id: "grid-4",
    slots: 4,
    build: ([a, b, c, d]) =>
      split("column", split("row", leaf(a), leaf(b)), split("row", leaf(c), leaf(d))),
  },
];

/** Sections offered to fill new tiles, after the ones already on screen. */
export const FILL_ORDER: readonly SectionId[] = [
  "agentic-ide", "agents", "chats", "memory", "docs", "sessions", "board", "clis",
  "visualization", "marketplace", "self-build",
];

/** `count` distinct, tileable sections: `first` ones kept, then FILL_ORDER. */
export function pickSections(first: readonly SectionId[], count: number): SectionId[] {
  const picked: SectionId[] = [];
  const owners = new Set<string>();
  for (const section of [...first, ...FILL_ORDER]) {
    if (picked.length >= count) break;
    if (!isTileable(section)) continue;
    const owner = sectionWindow(section);
    if (owners.has(owner)) continue;
    owners.add(owner);
    picked.push(section);
  }
  return picked;
}

/** A stored tree, checked: unknown shapes or sections give null. */
export function parseTree(value: unknown, isSection: (v: unknown) => v is SectionId): TileNode | null {
  const seen = new Set<string>();
  const walk = (raw: unknown, depth: number): TileNode | null => {
    if (!raw || typeof raw !== "object" || depth > 8) return null;
    const item = raw as Record<string, unknown>;
    if (item.kind === "leaf") {
      if (!isSection(item.section) || !isTileable(item.section)) return null;
      const owner = sectionWindow(item.section);
      if (seen.has(owner)) return null;
      seen.add(owner);
      return { kind: "leaf", id: tileId("l"), section: item.section };
    }
    if (item.kind === "split" && (item.dir === "row" || item.dir === "column")) {
      const a = walk(item.a, depth + 1);
      const b = walk(item.b, depth + 1);
      if (!a || !b) return a ?? b;
      return { kind: "split", id: tileId("s"), dir: item.dir, ratio: clampRatio(Number(item.ratio)), a, b };
    }
    return null;
  };
  const tree = walk(value, 0);
  return tree && leaves(tree).length >= 2 && leaves(tree).length <= MAX_TILES ? tree : null;
}
