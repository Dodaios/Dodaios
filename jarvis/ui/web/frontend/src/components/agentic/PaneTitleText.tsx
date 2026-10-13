import { useLayoutEffect, useRef, useState, type CSSProperties, type HTMLAttributes } from "react";

/** The fade a title too wide for its row ends in; alpha only, so it suits every pane ground. */
const FADE = "linear-gradient(to right, #000 calc(100% - 1.75rem), transparent)";

/**
 * A pane's title on one line, written out for as far as its row is wide.
 *
 * A title wider than the row fades out at the edge; it is never cut to an
 * ellipsis, and one that fits is drawn untouched. `data-clipped` says which of
 * the two is on screen, for the row that offers the whole title on hover.
 */
export function PaneTitleText({ text, className = "", style, ...rest }: { text: string } & HTMLAttributes<HTMLSpanElement>) {
  const ref = useRef<HTMLSpanElement>(null);
  const [clipped, setClipped] = useState(false);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    // A pixel of slack: both widths are rounded, and a title that fits must not fade.
    const measure = () => setClipped(node.scrollWidth - node.clientWidth > 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [text]);

  const fade: CSSProperties = clipped ? { maskImage: FADE, WebkitMaskImage: FADE } : {};
  return <span ref={ref} {...rest} data-clipped={clipped ? "true" : undefined}
    className={`min-w-0 overflow-hidden whitespace-nowrap ${className}`}
    style={{ ...style, ...fade }}>{text}</span>;
}
