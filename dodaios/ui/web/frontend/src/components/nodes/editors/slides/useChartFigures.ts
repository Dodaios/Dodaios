/**
 * The drawn figure of every chart slide, fetched from the server's chart
 * renderer (`deckPage.loadChartFigure`) as the charts change.
 *
 * A figure depends on the chart and on the slide's title (the page leaves
 * out a chart title that repeats the slide's), so typing a chart slide's
 * title or editing its chart asks for a new figure. Those requests wait a
 * moment for the typing to settle, and until the new figure is there the
 * slide keeps showing its previous one: a chart never blinks out while the
 * person works.
 */
import { useEffect, useRef, useState } from "react";

import type { Slide } from "./deckModel";
import { cachedFigure, chartKey, loadChartFigure } from "./deckPage";

const SETTLE_MS = 250;
const RETRY_MS = 4_000;

/** Per slide index: the figure to draw, or null while there is none yet. */
export function useChartFigures(nodeId: string, slides: readonly Slide[]): (index: number) => string | null {
  const [, setTick] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const last = useRef(new Map<number, string>());

  const wanted = slides
    .map((slide) => (slide.layout === "chart" && slide.chart ? chartKey(slide.chart, slide.title) : ""))
    .join("\n");

  useEffect(() => {
    let live = true;
    const missing = slides.filter((slide) => slide.layout === "chart" && slide.chart && cachedFigure(chartKey(slide.chart, slide.title)) === undefined);
    if (!missing.length) return;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const timer = setTimeout(() => {
      void Promise.allSettled(missing.map((slide) => loadChartFigure(nodeId, slide.chart!, slide.title))).then((results) => {
        if (!live) return;
        setTick((tick) => tick + 1);
        // The server was not reachable for some: ask again a little later.
        if (results.some((result) => result.status === "rejected")) retry = setTimeout(() => setAttempt((n) => n + 1), RETRY_MS);
      });
    }, SETTLE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
      if (retry !== undefined) clearTimeout(retry);
    };
    // `wanted` stands for the chart content of the slides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, wanted, attempt]);

  return (index: number) => {
    const slide = slides[index];
    if (!slide || slide.layout !== "chart" || !slide.chart) return null;
    const figure = cachedFigure(chartKey(slide.chart, slide.title));
    if (figure !== undefined) {
      last.current.set(index, figure);
      return figure;
    }
    return last.current.get(index) ?? null;
  };
}
