/**
 * The side panel's split layout: a tree of panes, each showing one open tab.
 *
 * A `row` lays its children out left to right, a `column` top to bottom.
 * `sizes` are the children's shares of the parent (they sum to 1). Every
 * function here is pure and returns a normalized tree: no split with a single
 * child, no split directly inside a split of the same direction, and `null`
 * once only one pane is left (the panel then shows one tab, unsplit).
 */

export type SplitDirection = "row" | "column";
/** Where a dragged tab lands on a pane: one of its edges, or the pane itself. */
export type DropZone = "left" | "right" | "top" | "bottom" | "center";

export interface LayoutLeaf<T extends string = string> {
  kind: "leaf";
  id: string;
  tab: T;
}

export interface LayoutSplit<T extends string = string> {
  kind: "split";
  id: string;
  direction: SplitDirection;
  children: LayoutNode<T>[];
  sizes: number[];
}

export type LayoutNode<T extends string = string> = LayoutLeaf<T> | LayoutSplit<T>;

/** More panes than this would leave each one too small to use. */
export const MAX_PANES = 6;
/** No pane shrinks below this share of its split when the dividers move. */
export const MIN_PANE_SHARE = 0.1;

let counter = 0;
export const newNodeId = (prefix: string) => `${prefix}${Date.now().toString(36)}${(counter++).toString(36)}`;

export const leaf = <T extends string>(tab: T, id = newNodeId("p")): LayoutLeaf<T> => ({ kind: "leaf", id, tab });

export function leaves<T extends string>(node: LayoutNode<T> | null): LayoutLeaf<T>[] {
  if (!node) return [];
  return node.kind === "leaf" ? [node] : node.children.flatMap((child) => leaves(child));
}

export const findLeafByTab = <T extends string>(node: LayoutNode<T> | null, tab: T) =>
  leaves(node).find((entry) => entry.tab === tab) ?? null;

export const findLeaf = <T extends string>(node: LayoutNode<T> | null, id: string) =>
  leaves(node).find((entry) => entry.id === id) ?? null;

const normalizeSizes = (sizes: number[]): number[] => {
  const total = sizes.reduce((sum, size) => sum + (size > 0 ? size : 0), 0);
  if (!total) return sizes.map(() => 1 / sizes.length);
  return sizes.map((size) => (size > 0 ? size : 0) / total);
};

/** Collapse single-child splits, flatten same-direction nesting, fix the sizes. */
export function normalize<T extends string>(node: LayoutNode<T> | null): LayoutNode<T> | null {
  if (!node || node.kind === "leaf") return node;
  const children: LayoutNode<T>[] = [];
  const sizes: number[] = [];
  node.children.forEach((child, index) => {
    const normal = normalize(child);
    if (!normal) return;
    const share = node.sizes[index] ?? 1 / node.children.length;
    if (normal.kind === "split" && normal.direction === node.direction) {
      normal.children.forEach((grandchild, inner) => {
        children.push(grandchild);
        sizes.push(share * normal.sizes[inner]);
      });
    } else {
      children.push(normal);
      sizes.push(share);
    }
  });
  if (children.length === 0) return null;
  if (children.length === 1) return children[0];
  return { ...node, children, sizes: normalizeSizes(sizes) };
}

/** The tree with `leafId` removed; its share goes to its siblings. */
export function removeLeaf<T extends string>(node: LayoutNode<T> | null, leafId: string): LayoutNode<T> | null {
  const strip = (current: LayoutNode<T>): LayoutNode<T> | null => {
    if (current.kind === "leaf") return current.id === leafId ? null : current;
    const kept: LayoutNode<T>[] = [];
    const sizes: number[] = [];
    current.children.forEach((child, index) => {
      const next = strip(child);
      if (next) {
        kept.push(next);
        sizes.push(current.sizes[index]);
      }
    });
    return { ...current, children: kept, sizes };
  };
  return node ? normalize(strip(node)) : null;
}

const directionOf = (zone: DropZone): SplitDirection => (zone === "left" || zone === "right" ? "row" : "column");
const before = (zone: DropZone) => zone === "left" || zone === "top";

/** The tree with a new pane for `tab` on the `zone` edge of `targetId`. */
export function insertBeside<T extends string>(
  node: LayoutNode<T>,
  targetId: string,
  tab: T,
  zone: Exclude<DropZone, "center">,
  newLeaf: LayoutLeaf<T> = leaf(tab),
): LayoutNode<T> {
  const direction = directionOf(zone);
  const place = (current: LayoutNode<T>): LayoutNode<T> => {
    if (current.kind === "leaf") {
      if (current.id !== targetId) return current;
      return {
        kind: "split",
        id: newNodeId("s"),
        direction,
        children: before(zone) ? [newLeaf, current] : [current, newLeaf],
        sizes: [0.5, 0.5],
      };
    }
    const index = current.children.findIndex((child) => child.kind === "leaf" && child.id === targetId);
    // A sibling in a split of the same direction: share the target's slot.
    if (index >= 0 && current.direction === direction) {
      const half = current.sizes[index] / 2;
      const children = [...current.children];
      const sizes = [...current.sizes];
      const at = before(zone) ? index : index + 1;
      sizes[index] = half;
      children.splice(at, 0, newLeaf);
      sizes.splice(at, 0, half);
      return { ...current, children, sizes };
    }
    return { ...current, children: current.children.map(place) };
  };
  return normalize(place(node)) ?? newLeaf;
}

export const replaceTab = <T extends string>(node: LayoutNode<T> | null, leafId: string, tab: T): LayoutNode<T> | null => {
  const swap = (current: LayoutNode<T>): LayoutNode<T> =>
    current.kind === "leaf"
      ? (current.id === leafId ? { ...current, tab } : current)
      : { ...current, children: current.children.map(swap) };
  return node ? swap(node) : null;
};

/** Drop every pane whose tab `keep` refuses (a closed tab, a shell of another window). */
export function prune<T extends string>(node: LayoutNode<T> | null, keep: (tab: T) => boolean): LayoutNode<T> | null {
  let next = node;
  const seen = new Set<T>();
  for (const entry of leaves(node)) {
    if (!keep(entry.tab) || seen.has(entry.tab)) next = removeLeaf(next, entry.id);
    seen.add(entry.tab);
  }
  return next;
}

/** Move the divider between child `index` and `index + 1` of split `splitId` to `share` of the split. */
export function resizeAt<T extends string>(node: LayoutNode<T> | null, splitId: string, index: number, share: number): LayoutNode<T> | null {
  const walk = (current: LayoutNode<T>): LayoutNode<T> => {
    if (current.kind === "leaf") return current;
    if (current.id !== splitId) return { ...current, children: current.children.map(walk) };
    const start = current.sizes.slice(0, index).reduce((sum, size) => sum + size, 0);
    const pair = current.sizes[index] + current.sizes[index + 1];
    const first = Math.min(pair - MIN_PANE_SHARE, Math.max(MIN_PANE_SHARE, share - start));
    if (!(pair > 2 * MIN_PANE_SHARE)) return current;
    const sizes = [...current.sizes];
    sizes[index] = first;
    sizes[index + 1] = pair - first;
    return { ...current, sizes };
  };
  return node ? walk(node) : null;
}

/** Even out the panes of split `splitId` (a divider's double-click). */
export function evenOut<T extends string>(node: LayoutNode<T> | null, splitId: string): LayoutNode<T> | null {
  const walk = (current: LayoutNode<T>): LayoutNode<T> =>
    current.kind === "leaf" ? current
      : current.id === splitId ? { ...current, sizes: current.children.map(() => 1 / current.children.length) }
        : { ...current, children: current.children.map(walk) };
  return node ? walk(node) : null;
}

/** A rectangle in shares of the whole panel area (0..1). */
export interface LayoutRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PlacedLeaf<T extends string = string> {
  leaf: LayoutLeaf<T>;
  rect: LayoutRect;
}

export interface PlacedDivider {
  splitId: string;
  /** Index of the child before the divider. */
  index: number;
  direction: SplitDirection;
  /** The divider line: x (row) or y (column) in panel shares, and its extent. */
  at: number;
  rect: LayoutRect;
  /** The split's own rectangle, to turn a pointer position into a share. */
  splitRect: LayoutRect;
}

/** Where every pane and every divider sits, in shares of the panel area. */
export function placeLayout<T extends string>(node: LayoutNode<T> | null): { leaves: PlacedLeaf<T>[]; dividers: PlacedDivider[] } {
  const placed: PlacedLeaf<T>[] = [];
  const dividers: PlacedDivider[] = [];
  const walk = (current: LayoutNode<T>, rect: LayoutRect) => {
    if (current.kind === "leaf") {
      placed.push({ leaf: current, rect });
      return;
    }
    let offset = 0;
    current.children.forEach((child, index) => {
      const share = current.sizes[index];
      const childRect = current.direction === "row"
        ? { x: rect.x + rect.w * offset, y: rect.y, w: rect.w * share, h: rect.h }
        : { x: rect.x, y: rect.y + rect.h * offset, w: rect.w, h: rect.h * share };
      walk(child, childRect);
      offset += share;
      if (index < current.children.length - 1) {
        const at = current.direction === "row" ? rect.x + rect.w * offset : rect.y + rect.h * offset;
        dividers.push({
          splitId: current.id,
          index,
          direction: current.direction,
          at,
          rect: current.direction === "row" ? { x: at, y: rect.y, w: 0, h: rect.h } : { x: rect.x, y: at, w: rect.w, h: 0 },
          splitRect: rect,
        });
      }
    });
  };
  if (node) walk(node, { x: 0, y: 0, w: 1, h: 1 });
  return { leaves: placed, dividers };
}

/** How many panes sit side by side at the widest point, to size the panel. */
export function columnCount(node: LayoutNode | null): number {
  if (!node || node.kind === "leaf") return 1;
  const counts = node.children.map(columnCount);
  return node.direction === "row" ? counts.reduce((sum, count) => sum + count, 0) : Math.max(...counts);
}

/** The zone of a pane under a pointer at (`fx`, `fy`) in shares of that pane. */
export function zoneAt(fx: number, fy: number, canSplit: boolean): DropZone {
  if (!canSplit) return "center";
  const dx = Math.min(fx, 1 - fx);
  const dy = Math.min(fy, 1 - fy);
  if (Math.min(dx, dy) > 0.25) return "center";
  if (dx <= dy) return fx < 0.5 ? "left" : "right";
  return fy < 0.5 ? "top" : "bottom";
}

/** Shape check for a stored layout; anything off is dropped rather than trusted. */
export function parseLayout<T extends string>(raw: unknown, isTab: (value: unknown) => value is T): LayoutNode<T> | null {
  const parse = (value: unknown, depth: number): LayoutNode<T> | null => {
    if (!value || typeof value !== "object" || depth > 8) return null;
    const node = value as Record<string, unknown>;
    if (typeof node.id !== "string") return null;
    if (node.kind === "leaf") return isTab(node.tab) ? { kind: "leaf", id: node.id, tab: node.tab } : null;
    if (node.kind !== "split" || (node.direction !== "row" && node.direction !== "column")) return null;
    const rawSizes = node.sizes;
    if (!Array.isArray(node.children) || !Array.isArray(rawSizes) || node.children.length !== rawSizes.length) return null;
    const children: LayoutNode<T>[] = [];
    const sizes: number[] = [];
    node.children.forEach((child, index) => {
      const parsed = parse(child, depth + 1);
      const size = Number(rawSizes[index]);
      if (parsed && Number.isFinite(size) && size > 0) {
        children.push(parsed);
        sizes.push(size);
      }
    });
    return { kind: "split", id: node.id, direction: node.direction, children, sizes };
  };
  const tree = normalize(parse(raw, 0));
  return leaves(tree).length > MAX_PANES ? null : tree;
}
