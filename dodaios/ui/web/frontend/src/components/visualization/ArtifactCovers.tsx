import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

/**
 * What a live miniature of a page needs to know about the box it sits in:
 * how wide to lay the page out, how big the box is, and whether it is near
 * the screen at all.
 *
 * Shared by the covers of the Nodes library (`components/nodes/covers`) and
 * the page card in a chat answer (`components/agentchat/PageCard`). A live
 * cover mounts only while its box is near the viewport, so a library of a
 * hundred dashboards costs what a screenful costs — and a WebGL map scrolled
 * out of view gives its context back (AP-32).
 */

/** The share of a tile's width one CSS pixel of a framed page is drawn at. */
const PAGE_TARGET_SCALE = 0.36;
/** A page is never laid out narrower or wider than this, whatever the tile. */
const PAGE_MIN_WIDTH = 680;
const PAGE_MAX_WIDTH = 1200;
/** Layout widths move in steps, so dragging the window does not re-flow every page per pixel. */
const PAGE_WIDTH_STEP = 40;

/** The width a page is laid out at for a tile this wide. */
export function pageVirtualWidth(tileWidth: number): number {
  const wanted = tileWidth / PAGE_TARGET_SCALE;
  const stepped = Math.round(wanted / PAGE_WIDTH_STEP) * PAGE_WIDTH_STEP;
  return Math.min(PAGE_MAX_WIDTH, Math.max(PAGE_MIN_WIDTH, stepped));
}

/**
 * True while the element is on, or about to scroll onto, the screen. Without
 * an IntersectionObserver (a test DOM) nothing is ever mounted — a cover then
 * stays its quiet placeholder, never a dozen live frames.
 */
export function useNearViewport(ref: RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => setNear(entries.some((entry) => entry.isIntersecting)),
      { rootMargin: "400px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return near;
}

/** The element's size, known before the first paint and kept current. */
export function useBoxSize(ref: RefObject<HTMLElement | null>): { width: number; height: number } {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = (width: number, height: number) =>
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    update(node.clientWidth, node.clientHeight);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      update(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
