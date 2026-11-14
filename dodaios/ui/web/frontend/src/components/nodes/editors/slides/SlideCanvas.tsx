/**
 * One slide drawn at the size of its box, inside a shadow root that carries
 * the deck page's own stylesheet (see `deckPage.ts` for why).
 *
 * A slide is laid out at a logical 1280 x 720 px and scaled as a whole with
 * `--k`, exactly as the page's player does it (rounded to whole pixels so
 * text stays sharp); the thumbnails, the editing canvas and the presenter
 * are the same component at different widths. After each render, a slide
 * body that overflows is set smaller step by step, as the page script does,
 * because the fonts of this machine decide the real line breaks.
 */
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

/**
 * The editor's own additions to the page's styles: the frame, and the editing
 * affordances. `all:initial` on the host keeps the app's inherited text
 * styles (letter spacing, alignment, line height) out of the slide, so only
 * the page's own rules shape it.
 */
const CANVAS_CSS = `
:host{all:initial;display:block}
.ed-stage{position:relative;overflow:hidden;font:16px/1.5 var(--font);color:var(--ink);text-align:left;
  background:var(--bg);-webkit-font-smoothing:antialiased;border-radius:inherit}
.ed-stage .sl{pointer-events:none}
.ed-stage.is-editable .sl{pointer-events:auto}
.ed-stage.is-editable [contenteditable]{outline:0;cursor:text;border-radius:calc(3px / var(--k));
  transition:box-shadow .12s ease}
.ed-stage.is-editable [contenteditable]:hover{
  box-shadow:0 0 0 calc(1px / var(--k)) color-mix(in srgb,var(--da) 45%,transparent)}
.ed-stage.is-editable [contenteditable]:focus{box-shadow:0 0 0 calc(2px / var(--k)) var(--da)}
.ed-stage [data-placeholder]:empty::before{content:attr(data-placeholder);color:var(--ink-3)}
.ed-stage a{pointer-events:none}
.ed-stage.is-presenting a{pointer-events:auto}
@media (prefers-reduced-motion:reduce){.ed-stage *{transition:none!important}}
`;

const supportsAdopted =
  typeof Document !== "undefined" &&
  "adoptedStyleSheets" in Document.prototype &&
  typeof CSSStyleSheet !== "undefined" &&
  "replaceSync" in CSSStyleSheet.prototype;

/** One constructed stylesheet per css text, shared by every shadow root (60 thumbnails, one parse). */
const sheets = new Map<string, CSSStyleSheet>();
function sheetFor(css: string): CSSStyleSheet | null {
  if (!supportsAdopted) return null;
  let sheet = sheets.get(css);
  if (!sheet) {
    sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    sheets.set(css, sheet);
  }
  return sheet;
}

/** Make every overflowing slide body inside `root` smaller until it fits (the page's `fitOne`). */
export function fitBodies(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>(".sl-body").forEach((body) => {
    body.style.fontSize = "";
    let size = parseFloat(getComputedStyle(body).fontSize);
    if (!Number.isFinite(size)) return;
    for (let i = 0; i < 14 && (body.scrollHeight > body.clientHeight + 1 || body.scrollWidth > body.clientWidth + 1); i++) {
      size *= 0.94;
      body.style.fontSize = `${size.toFixed(2)}px`;
    }
  });
}

export interface SlideCanvasProps {
  /** The page's stylesheet, already rewritten for a shadow root. */
  css: string;
  /** Box width in CSS pixels; omitted, the canvas fills its parent's width. */
  width?: number;
  /** The theme the slide is drawn in. */
  theme: "light" | "dark";
  /** The deck's accent as a CSS color, or "" for the kit's. */
  accent: string;
  /** Typing on the slide is allowed (the editing canvas). */
  editable?: boolean;
  presenting?: boolean;
  className?: string;
  style?: CSSProperties;
  /** Fires with the drawn width, so a caller can size things around it. */
  onWidth?: (width: number) => void;
  testId?: string;
  children: ReactNode;
}

export function SlideCanvas({
  css,
  width: fixedWidth,
  theme,
  accent,
  editable = false,
  presenting = false,
  className,
  style,
  onWidth,
  testId,
  children,
}: SlideCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [mount, setMount] = useState<HTMLDivElement | null>(null);
  const styleRef = useRef<HTMLStyleElement | null>(null);
  const [measured, setMeasured] = useState(0);

  // The shadow root and the node React draws into, made once per host.
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const shadow = host.shadowRoot ?? host.attachShadow({ mode: "open" });
    const stage = document.createElement("div");
    shadow.appendChild(stage);
    setMount(stage);
    return () => {
      stage.remove();
      styleRef.current?.remove();
      styleRef.current = null;
    };
  }, []);

  // The stylesheets: shared constructed sheets where the engine has them, a <style> otherwise.
  useLayoutEffect(() => {
    const shadow = hostRef.current?.shadowRoot;
    if (!shadow) return;
    const page = sheetFor(css);
    const own = sheetFor(CANVAS_CSS);
    if (page && own) {
      shadow.adoptedStyleSheets = [page, own];
      return;
    }
    if (!styleRef.current) {
      styleRef.current = document.createElement("style");
      shadow.insertBefore(styleRef.current, shadow.firstChild);
    }
    styleRef.current.textContent = `${css}\n${CANVAS_CSS}`;
  }, [css, mount]);

  // A canvas without a fixed width follows its box.
  useLayoutEffect(() => {
    if (fixedWidth !== undefined) return;
    const host = hostRef.current;
    if (!host) return;
    const read = () => setMeasured(host.clientWidth);
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(host);
    return () => observer.disconnect();
  }, [fixedWidth]);

  const raw = fixedWidth ?? measured;
  // Whole pixels, like the page's player: the slide's width, then the scale from it.
  const width = Math.max(1, Math.round(raw));
  const k = width / 1280;
  const height = Math.round(720 * k);

  useLayoutEffect(() => {
    onWidth?.(width);
  }, [onWidth, width]);

  // After every render: the page's overflow fitting.
  useLayoutEffect(() => {
    if (mount) fitBodies(mount);
  });

  // Fonts that arrive later change the line breaks: fit once more then.
  useLayoutEffect(() => {
    if (!mount || typeof document === "undefined" || !document.fonts?.ready) return;
    let live = true;
    void document.fonts.ready.then(() => {
      if (live) fitBodies(mount);
    });
    return () => {
      live = false;
    };
  }, [mount]);

  const stageStyle = {
    width,
    height,
    "--k": k.toFixed(5),
    "--da": accent || "var(--accent)",
  } as CSSProperties;

  return (
    <div
      ref={hostRef}
      data-theme={theme}
      data-testid={testId}
      className={cn("relative block", className)}
      style={{ ...style, height: fixedWidth === undefined ? undefined : height }}
    >
      {mount &&
        createPortal(
          <div className={cn("ed-stage", editable && "is-editable", presenting && "is-presenting")} style={stageStyle}>
            {raw > 0 && children}
          </div>,
          mount,
        )}
    </div>
  );
}
