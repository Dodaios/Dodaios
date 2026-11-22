/**
 * A visual an answer carries, DRAWN the way the reader expects a picture to
 * appear: a fenced `html` / `svg` block, a diagram, or a self-contained page
 * an agent linked. Shown as a code block, the "picture" is a wall of angle
 * brackets. Here it draws as a figure that takes the height of what is in it,
 * with its source, a copy button and a full view one click away.
 *
 * Safety is the artifact page's model, mirrored for inline markup:
 * - Every visual renders in an `<iframe srcdoc>` whose sandbox never has
 *   `allow-same-origin`, so it lives in an opaque origin that cannot reach the
 *   app's cookies, storage or API.
 * - A Content-Security-Policy is the first thing in the document. It blocks
 *   every subresource fetch (`INLINE_HTML_CSP`, the verbatim twin of
 *   `ARTIFACT_PAGE_CSP` in `dodaios/ui/web/artifact_view.py`).
 * - The visual's OWN scripts do not run by default. The policy then allows
 *   one script only, by a nonce made for this frame: the size reporter the
 *   frame is given, so the figure can take its content's height. Markup
 *   written before the nonce existed cannot carry it, and the policy stands
 *   in front of all of it, so nothing the author wrote runs: no script tag,
 *   no handler attribute, no `javascript:` address.
 * - The visual's scripts run only after an explicit "Run scripts" click.
 *   CSP cannot stop a script from navigating its own frame
 *   (`location.href = "https://..."`), so a running snippet CAN reach a web
 *   address; that is why running is the reader's choice, never the default
 *   (issue #346).
 * - The parent trusts a size message only from that frame's own window, with
 *   that frame's token, and only up to a ceiling.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Check, Code2, Copy, Eye, Maximize2, Play, X } from "lucide-react";

import { robustCopy } from "@/lib/clipboard";
import { useT } from "@/i18n";
import { useThemeValue, type Theme } from "@/hooks/useTheme";
import { CodeBlock } from "@/components/docs/CodeBlock";

export type FenceLanguage = "html" | "svg";

/** Twin of `ARTIFACT_PAGE_CSP` (dodaios/ui/web/artifact_view.py) — keep in step. */
export const INLINE_HTML_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; " +
  "form-action 'none'; frame-src 'none'; base-uri 'none';";

/** The message type the size reporter posts with the document's height. */
export const INLINE_HTML_SIZE_MESSAGE = "jarvis-inline-html-size";

const MIN_FRAME_PX = 40;
/** A taller visual scrolls inside its figure; the full view shows all of it. */
const MAX_FRAME_PX = 640;
/** The figure's height until its frame reports the real one. */
const START_FRAME_PX = 160;

/**
 * The colours a visual can name instead of fixing its own: `var(--fg)` and
 * so on. The agents are told these names (`dodaios/agent_chat/thread_visuals.py`,
 * pinned by a parity test), so a drawing made with them reads in both palettes.
 */
export const VISUAL_TOKENS = ["fg", "muted", "line", "surface", "accent", "ok", "warn", "bad"] as const;
type Token = (typeof VISUAL_TOKENS)[number];
export type VisualSkin = Record<Token, string>;

/** A drawing that fixes its own colours expects a white page: it gets one, in both palettes. */
const PAPER: VisualSkin = {
  fg: "#171717", muted: "#545454", line: "#c4c4c4", surface: "#f5f5f5",
  accent: "#096cdc", ok: "#15803d", warn: "#a95c04", bad: "#c52020",
};
const DARK: VisualSkin = {
  fg: "#fafafa", muted: "#ababab", line: "#4d4d4d", surface: "#1f1f1f",
  accent: "#3d8bff", ok: "#22c35e", warn: "#f59e0b", bad: "#df3a3a",
};
/** Where each token comes from in the app's own palette. */
const APP_TOKENS: Record<Token, string> = {
  fg: "--foreground", muted: "--muted-foreground", line: "--border-strong", surface: "--secondary",
  accent: "--accent", ok: "--success", warn: "--warning", bad: "--destructive",
};

/**
 * The app's palette as the visual's colours, read from the page so a design
 * the person made carries into the drawing. Where the page cannot say
 * (a test, a missing token) the built-in palette of that theme stands in.
 */
export function appSkin(theme: Theme): VisualSkin {
  const fallback = theme === "dark" ? DARK : PAPER;
  if (typeof document === "undefined" || !document.body) return fallback;
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.body.appendChild(probe);
  const skin = { ...fallback };
  try {
    for (const token of VISUAL_TOKENS) {
      probe.style.color = "";
      probe.style.color = `hsl(var(${APP_TOKENS[token]}))`;
      const colour = getComputedStyle(probe).color;
      if (/^rgba?\(\s*\d/.test(colour)) skin[token] = colour;
    }
  } finally {
    probe.remove();
  }
  return skin;
}

/** The colour of the surface a themed visual stands on (the figure's own), for what must cover a line behind it. */
export function appSurface(theme: Theme): string {
  const fallback = theme === "dark" ? "#171717" : "#ffffff";
  if (typeof document === "undefined" || !document.body) return fallback;
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = "hsl(var(--card))";
  document.body.appendChild(probe);
  try {
    const colour = getComputedStyle(probe).color;
    return /^rgba?\(\s*\d/.test(colour) ? colour : fallback;
  } finally {
    probe.remove();
  }
}

const THEME_AWARE = new RegExp(`var\\(\\s*--(?:${VISUAL_TOKENS.join("|")})\\b|data-theme|prefers-color-scheme|light-dark\\(`, "i");

/**
 * Whether a visual follows the palette it is shown in: it names the colours
 * above, or brings a light and a dark look of its own. Such a visual draws
 * straight on the app's surface; any other one draws on a white page.
 */
export function isThemeAware(code: string): boolean {
  return THEME_AWARE.test(code);
}

/** The words in a visual's `<title>`, when it has one: the figure's caption. */
export function visualTitle(code: string): string {
  const match = /<title[^>]*>([^<]{1,160})<\/title>/i.exec(code);
  return match ? match[1].replace(/\s+/g, " ").trim() : "";
}

/** Whether a page has anything that would run: a script or a handler attribute. */
export function hasScripts(code: string): boolean {
  return /<script[\s>]/i.test(code) || /<[a-z][^>]*\son[a-z]+\s*=/i.test(code);
}

/** An SVG that gives a size and no view box cannot scale down; its size becomes its view box. */
export function scalableSvg(svg: string): string {
  return svg.replace(/<svg(?=[\s>])[^>]*>/i, (root) => {
    if (/\sviewBox\s*=/i.test(root)) return root;
    const size = (name: string) => new RegExp(`\\s${name}\\s*=\\s*["']?\\s*([0-9.]+)(?:px)?\\s*["']?[\\s>/]`, "i").exec(root)?.[1];
    const width = size("width");
    const height = size("height");
    return width && height ? root.replace(/^<svg/i, `<svg viewBox="0 0 ${width} ${height}"`) : root;
  });
}

/** A value no page written beforehand can know. */
function makeNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function reporterScript(token: string): string {
  const safe = token.replace(/[^\w:-]/g, "");
  return (
    "(function(){function h(){var d=document.documentElement,b=document.body;" +
    "return Math.ceil(Math.max(d.offsetHeight,b?b.scrollHeight:0,b?b.offsetHeight:0))}" +
    `function r(){try{parent.postMessage({type:"${INLINE_HTML_SIZE_MESSAGE}",token:"${safe}",` +
    'height:h()},"*")}catch(e){}}' +
    "try{new ResizeObserver(r).observe(document.documentElement)}catch(e){}" +
    'addEventListener("DOMContentLoaded",r);addEventListener("load",r);r()})();'
  );
}

export interface VisualDocumentOptions {
  language?: FenceLanguage;
  /** The app's palette right now. */
  theme: Theme;
  /** Names this frame's size messages. */
  token: string;
  /** Allows the size reporter while the visual's own scripts are off. */
  nonce: string;
  /** The reader asked for the visual's own scripts. */
  scripts?: boolean;
  /** Draws on the app's surface in its colours; left out, the visual says so itself (`isThemeAware`). */
  themed?: boolean;
  skin?: VisualSkin;
}

/**
 * The document the frame loads. The policy, the colours and the size reporter
 * come first, in front of everything the author wrote; a whole page follows
 * as it is, a fragment or a bare `<svg>` is set in a minimal page. Exported
 * for the tests.
 */
export function visualDocument(code: string, options: VisualDocumentOptions): string {
  const { language = "html", theme, token, nonce, scripts = false } = options;
  const themed = options.themed ?? isThemeAware(code);
  const look: Theme = themed ? theme : "light";
  const skin = options.skin ?? (themed ? appSkin(theme) : PAPER);
  const policy = scripts ? INLINE_HTML_CSP : INLINE_HTML_CSP.replace("script-src 'unsafe-inline'", `script-src 'nonce-${nonce}'`);
  const colours = VISUAL_TOKENS.map((name) => `--${name}:${skin[name]}`).join(";");
  const head =
    '<meta charset="utf-8">' +
    `<meta http-equiv="Content-Security-Policy" content="${policy}">` +
    `<style>:root{${colours};color-scheme:${look}}</style>` +
    `<script nonce="${nonce}">${reporterScript(token)}</script>`;
  if (language === "html" && /<html[\s>]/i.test(code)) {
    // The page's own doctype would come too late to count; ours already stands.
    let page = code.replace(/^\s*<!doctype[^>]*>/i, "");
    if (!/<html[^>]*\sdata-theme=/i.test(page)) {
      page = page.replace(/<html(\s[^>]*)?>/i, (_match, attrs: string | undefined) => `<html${attrs ?? ""} data-theme="${look}">`);
    }
    return `<!doctype html>${head}${page}`;
  }
  const body = language === "svg" ? scalableSvg(code) : code;
  return (
    `<!doctype html><html lang="en" data-theme="${look}"><head>${head}<style>` +
    "html,body{margin:0}" +
    `body{padding:${language === "svg" ? "12px" : "16px"};color:var(--fg);` +
    'font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;overflow-wrap:anywhere}' +
    "body>:first-child{margin-top:0}body>:last-child{margin-bottom:0}" +
    "svg,img,canvas,video{max-width:100%;height:auto}" +
    (language === "svg" ? "body>svg{display:block;margin:0 auto}" : "") +
    `</style></head><body>${body}</body></html>`
  );
}

/**
 * The sandboxed frame a visual renders in. It takes the height its content
 * reports; `fill` (the full view) takes the height it is given instead.
 */
export function InlineHtmlFrame({
  html,
  title,
  language = "html",
  scripts = false,
  themed,
  fill = false,
}: {
  html: string;
  title: string;
  language?: FenceLanguage;
  scripts?: boolean;
  themed?: boolean;
  fill?: boolean;
}) {
  const theme = useThemeValue();
  const token = useId().replace(/[^\w:-]/g, "");
  const [nonce] = useState(makeNonce);
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(START_FRAME_PX);
  const onSurface = themed ?? isThemeAware(html);

  useEffect(() => {
    if (fill) return;
    const onMessage = (event: MessageEvent) => {
      const frame = ref.current;
      if (!frame || event.source !== frame.contentWindow) return;
      const data: unknown = event.data;
      if (
        typeof data !== "object" ||
        data === null ||
        (data as { type?: unknown }).type !== INLINE_HTML_SIZE_MESSAGE ||
        (data as { token?: unknown }).token !== token
      ) {
        return;
      }
      const reported = Number((data as { height?: unknown }).height);
      if (!Number.isFinite(reported)) return;
      setHeight(Math.min(MAX_FRAME_PX, Math.max(MIN_FRAME_PX, Math.ceil(reported))));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [token, fill]);

  const doc = useMemo(
    () => visualDocument(html, { language, theme, token, nonce, scripts, themed: onSurface }),
    [html, language, theme, token, nonce, scripts, onSurface],
  );

  return (
    <iframe
      ref={ref}
      key={`${theme}-${scripts ? "scripts" : "inert"}`}
      title={title}
      srcDoc={doc}
      // Never `allow-same-origin`: the frame stays in an opaque origin.
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      style={{ height: fill ? "100%" : height, background: onSurface ? "transparent" : "#fff" }}
      data-scripts={scripts ? "on" : "off"}
      data-look={onSurface ? "themed" : "paper"}
      className="block w-full border-0"
      data-testid="inline-html-frame"
    />
  );
}

const FIGURE = "not-prose group/visual relative my-4 overflow-hidden rounded-xl border border-border bg-card";
const TOOL = "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** A visual's place while its block is still being written, so no half-drawn markup flickers by. */
export function RenderedFencePending() {
  const t = useT();
  return (
    <figure className={FIGURE} data-testid="rendered-fence-pending" role="status" aria-label={t("outputs_view.visual_pending")}>
      <div className="flex h-40 flex-col justify-center gap-3 px-6">
        <div className="h-3 w-2/5 animate-pulse rounded-full bg-foreground/10 motion-reduce:animate-none" />
        <div className="h-16 animate-pulse rounded-lg bg-foreground/[0.07] motion-reduce:animate-none" />
        <div className="h-3 w-3/5 animate-pulse rounded-full bg-foreground/10 motion-reduce:animate-none" />
      </div>
      <figcaption className="border-t border-border px-3 py-2 text-xs text-muted-foreground">{t("outputs_view.visual_pending")}</figcaption>
    </figure>
  );
}

export function RenderedFence({
  language,
  code,
  title,
  source,
  sourceLanguage,
  themed,
  action,
}: {
  language: FenceLanguage;
  code: string;
  /** The figure's caption; a visual's own `<title>` when left out. */
  title?: string;
  /** What Source and Copy show, when the drawing was made from something else (a diagram's text). */
  source?: string;
  sourceLanguage?: string;
  themed?: boolean;
  /** What stands at the end of the figure's foot: a stored page's download. */
  action?: ReactNode;
}) {
  const t = useT();
  const [mode, setMode] = useState<"rendered" | "source">("rendered");
  const [copied, setCopied] = useState(false);
  const [scripts, setScripts] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const written = source ?? code;
  const caption = title ?? visualTitle(code);
  const name = caption || (sourceLanguage ?? language).toUpperCase();
  const runnable = language === "html" && hasScripts(code);
  const offersRun = runnable && !scripts && mode === "rendered";

  const copy = () => {
    void robustCopy(written).then((ok) => {
      if (!ok) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <Dialog.Root open={expanded} onOpenChange={setExpanded}>
      <figure className={FIGURE} data-testid="rendered-fence" data-language={sourceLanguage ?? language} data-mode={mode}>
        {/* The tools stay out of the picture until the reader points at it; a touch screen always shows them. */}
        <div className="absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-lg border border-border bg-popover p-0.5 opacity-0 shadow-sm transition-opacity focus-within:opacity-100 group-hover/visual:opacity-100 [@media(hover:none)]:opacity-100">
          <button type="button" className={TOOL} onClick={() => setMode(mode === "rendered" ? "source" : "rendered")}
            aria-label={t(mode === "rendered" ? "outputs_view.fence_source" : "outputs_view.fence_rendered")}
            title={t(mode === "rendered" ? "outputs_view.fence_source" : "outputs_view.fence_rendered")}>
            {mode === "rendered" ? <Code2 className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
          </button>
          <button type="button" className={TOOL} onClick={copy}
            title={t("docs_content.copy_code")} aria-label={copied ? t("docs_content.code_copied") : t("docs_content.copy_code")}>
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          </button>
          <Dialog.Trigger asChild>
            <button type="button" className={TOOL} title={t("outputs_view.visual_expand")} aria-label={t("outputs_view.visual_expand")} data-testid="visual-expand">
              <Maximize2 className="h-3.5 w-3.5" aria-hidden />
            </button>
          </Dialog.Trigger>
        </div>
        {mode === "source" ? (
          <CodeBlock language={sourceLanguage ?? language} code={written} chrome={false} />
        ) : (
          <InlineHtmlFrame html={code} title={name} language={language} scripts={scripts} themed={themed} />
        )}
        {/* One foot at most: what the figure is, and what the reader can do with it. */}
        {caption || offersRun || action ? (
          <figcaption className="flex min-h-9 items-center gap-3 border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
            <span className="min-w-0 flex-1 truncate">{caption || (offersRun ? t("outputs_view.fence_scripts_off") : "")}</span>
            {offersRun ? (
              <button type="button" onClick={() => setScripts(true)} data-testid="inline-html-run-scripts"
                title={caption ? `${t("outputs_view.fence_scripts_off")} ${t("outputs_view.fence_run_scripts_hint")}` : t("outputs_view.fence_run_scripts_hint")}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-0.5 font-medium text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Play className="h-3 w-3" aria-hidden />{t("outputs_view.fence_run_scripts")}
              </button>
            ) : null}
            {action}
          </figcaption>
        ) : null}
      </figure>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-background/90" />
        <Dialog.Content aria-describedby={undefined} data-testid="visual-full-view"
          className="fixed inset-4 z-50 flex flex-col overflow-hidden rounded-xl border border-border bg-card text-foreground shadow-xl sm:inset-8">
          <div className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2.5">
            <Dialog.Title className="min-w-0 flex-1 truncate text-sm">{name}</Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="rounded p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <X aria-hidden className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1">
            <InlineHtmlFrame html={code} title={name} language={language} scripts={scripts} themed={themed} fill />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
