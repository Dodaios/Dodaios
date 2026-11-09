import { useEffect, useState, type RefObject } from "react";
import type { PanelGeometry } from "./streamSession";

/**
 * Whether the panel is really on screen, and its size (WP20.3).
 *
 * Visible means: intersecting the viewport (`IntersectionObserver`), the page not hidden (page
 * visibility: minimised app, other window in front of a hidden WebView), and a non-zero size.
 * Every change lands in the same task as the browser's event, so a hidden panel closes its
 * stream at once.
 */
export function usePanelVisibility(ref: RefObject<HTMLElement | null>): { visible: boolean; geometry: PanelGeometry } {
  const [intersecting, setIntersecting] = useState(false);
  const [pageVisible, setPageVisible] = useState(() => typeof document === "undefined" || document.visibilityState !== "hidden");
  const [geometry, setGeometry] = useState<PanelGeometry>({ w: 0, h: 0, dpr: 1 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const next = {
        w: Math.round(rect.width),
        h: Math.round(rect.height),
        dpr: Math.round((window.devicePixelRatio || 1) * 100) / 100,
      };
      setGeometry((prev) => (prev.w === next.w && prev.h === next.h && prev.dpr === next.dpr ? prev : next));
    };
    measure();

    let intersection: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      intersection = new IntersectionObserver(
        (entries) => {
          const entry = entries[entries.length - 1];
          if (entry) setIntersecting(entry.isIntersecting && entry.intersectionRatio > 0);
        },
        { threshold: [0, 0.01] },
      );
      intersection.observe(element);
    } else {
      setIntersecting(true);
    }

    let resize: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      resize = new ResizeObserver(measure);
      resize.observe(element);
    }
    window.addEventListener("resize", measure);

    const onPage = () => setPageVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", onPage);
    return () => {
      intersection?.disconnect();
      resize?.disconnect();
      window.removeEventListener("resize", measure);
      document.removeEventListener("visibilitychange", onPage);
    };
  }, [ref]);

  return { visible: intersecting && pageVisible && geometry.w > 0 && geometry.h > 0, geometry };
}
