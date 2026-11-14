/**
 * What the editor borrows from the deck's real page: its stylesheet, and the
 * drawn figure of each chart.
 *
 * The editor draws slides itself (`SlideView`), with the same markup as
 * `slides.py`, so typing on a slide and switching slides is instant. For the
 * slides to look EXACTLY like the page, it does not copy the page's styles:
 * it asks the server for a page (`POST /api/nodes/{id}/preview`, a tiny
 * one-slide spec) and takes the `<style>` from it. A later change to the
 * deck's look reaches the editor without touching it.
 *
 * The slides are drawn inside shadow roots (`SlideCanvas`), which keeps the
 * page's element rules (`h1`, `p`, `*`) and the app's own styles apart in
 * both directions. A shadow root has no `:root`, so the page's theme tokens
 * are moved onto `:host`, where the canvas sets `data-theme`.
 *
 * Charts are drawn by the server's chart renderer (`report_blocks`), the
 * same SVG the page holds, fetched per chart and kept in a small cache.
 */
import { fetchNodePreview } from "../api";

import type { DeckChart } from "./deckModel";

/** `:root`, `:root[x]`, `:root:not(…)` → `:host`, `:host([x])`, `:host(:not(…))`. */
const ROOT_RE = /:root((?:\[[^\]]*\]|:not\((?:[^()]|\([^()]*\))*\))*)/g;

export function cssForShadow(css: string): string {
  return css.replace(ROOT_RE, (_match, qualifiers: string) => (qualifiers ? `:host(${qualifiers})` : ":host"));
}

/** Every `<style>` of a page, in order. */
export function stylesOf(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  return Array.from(doc.querySelectorAll("style"))
    .map((style) => style.textContent ?? "")
    .join("\n");
}

/** The smallest deck the server accepts: only its stylesheet is wanted. */
const STYLE_PROBE = { slides: [{ layout: "title", title: "·" }] };

let stylesheet: Promise<string> | null = null;

/**
 * The deck page's stylesheet, ready for a shadow root. Fetched once per app
 * session (it is the same for every deck); a failure is not cached, so the
 * next editor that opens tries again.
 */
export function loadDeckCss(nodeId: string): Promise<string> {
  if (!stylesheet) {
    stylesheet = fetchNodePreview(nodeId, STYLE_PROBE).then(
      (html) => cssForShadow(stylesOf(html)),
      (error: unknown) => {
        stylesheet = null;
        throw error;
      },
    );
  }
  return stylesheet;
}

/** For tests: forget the fetched stylesheet and the chart figures. */
export function resetDeckPageCache(): void {
  stylesheet = null;
  figures.clear();
  pending.clear();
}

// --- chart figures ---------------------------------------------------------------

/** What makes a chart's figure: the chart, and the slide title it is drawn under. */
export function chartKey(chart: DeckChart | undefined, title: string | undefined): string {
  return JSON.stringify([chart ?? null, (title ?? "").toLocaleLowerCase()]);
}

const FIGURE_CACHE_SIZE = 120;
const figures = new Map<string, string>();
const pending = new Map<string, Promise<string>>();

/** The figure for `key` if it was drawn already (the empty string means "cannot be drawn"). */
export function cachedFigure(key: string): string | undefined {
  return figures.get(key);
}

function remember(key: string, html: string): void {
  if (figures.size >= FIGURE_CACHE_SIZE) {
    const oldest = figures.keys().next().value;
    if (oldest !== undefined) figures.delete(oldest);
  }
  figures.set(key, html);
}

/**
 * The chart's figure as the page draws it (the inner HTML of `.sl-plot`).
 * Resolves to "" when the server cannot draw the chart; rejects only when
 * the server cannot be reached, so the caller can try again later.
 */
export function loadChartFigure(nodeId: string, chart: DeckChart, title: string | undefined): Promise<string> {
  const key = chartKey(chart, title);
  const known = figures.get(key);
  if (known !== undefined) return Promise.resolve(known);
  const running = pending.get(key);
  if (running) return running;
  const slide: Record<string, unknown> = { layout: "chart", chart };
  if (title) slide.title = title;
  const request = fetchNodePreview(nodeId, { slides: [slide] })
    .then(
      (html) => {
        const doc = new DOMParser().parseFromString(html, "text/html");
        return doc.querySelector(".sl-plot")?.innerHTML ?? "";
      },
      (error: unknown) => {
        // A chart the server refuses (422) has no figure; anything else may pass.
        if (error && typeof error === "object" && (error as { status?: number }).status === 422) return "";
        throw error;
      },
    )
    .then((html) => {
      remember(key, html);
      return html;
    })
    .finally(() => pending.delete(key));
  pending.set(key, request);
  return request;
}
