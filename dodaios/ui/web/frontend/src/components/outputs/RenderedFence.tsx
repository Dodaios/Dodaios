/**
 * A fenced `html` / `svg` block DRAWN, the way the reader expects a picture
 * to appear, with its source one click away.
 *
 * A worker that answers with a chart or a diagram writes it as inline SVG or
 * a self-contained HTML snippet (the artifact brief tells it to); shown as a
 * code block, the "picture" is a wall of angle brackets. Here the block
 * renders by default and a Rendered / Source switch in its header shows the
 * markup for whoever wants it.
 *
 * Safety is the artifact page's model, mirrored for inline markup:
 * - SVG is drawn through an `<img>` from a data: URL — a browser never runs
 *   script or fetches anything for an SVG-as-image.
 * - HTML renders INERT by default: an `<iframe srcdoc>` with an empty
 *   `sandbox` (no scripts, no same-origin, no forms, no popups) plus a
 *   Content-Security-Policy stamped into the document (`INLINE_HTML_CSP`, the
 *   verbatim twin of `ARTIFACT_PAGE_CSP` in `dodaios/ui/web/artifact_view.py`)
 *   that blocks every subresource fetch. A fence shows up in a chat on its
 *   own, so nothing in it may run or reach the network before the reader
 *   asks for it.
 * - Scripts run only after an explicit "Run scripts" click. The frame then
 *   gets `sandbox="allow-scripts"` (still NO `allow-same-origin`, so it lives
 *   in an opaque origin that cannot reach the app's cookies, storage or API).
 *   CSP cannot stop a script from navigating its own frame
 *   (`location.href = "https://..."`), so a running snippet CAN reach a web
 *   address; that is why running is the reader's choice, never the default
 *   (issue #346). The scripted frame grows to its content through a
 *   `postMessage` the injected reporter sends; the parent trusts a message
 *   only from that frame's own window, and only up to a ceiling.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";
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

/** The message type the injected reporter posts with the document's height. */
export const INLINE_HTML_SIZE_MESSAGE = "jarvis-inline-html-size";

const MIN_FRAME_PX = 96;
const MAX_FRAME_PX = 720;
/** Height of an inert frame: without a script nothing can report the content's size. */
const INERT_FRAME_PX = 320;

/** The app's card surface in each palette, for a fragment that brings no page of its own. */
const FRAGMENT_SKIN: Record<Theme, { bg: string; ink: string }> = {
  light: { bg: "#ffffff", ink: "#141413" },
  dark: { bg: "#30302e", ink: "#f5f4ef" },
};

function headBits(): string {
  return (
    '<meta charset="utf-8">' +
    `<meta http-equiv="Content-Security-Policy" content="${INLINE_HTML_CSP}">`
  );
}

function reporterScript(token: string): string {
  const safe = token.replace(/[^\w:-]/g, "");
  return (
    "<script>(function(){var h=document.documentElement;function r(){try{" +
    `parent.postMessage({type:"${INLINE_HTML_SIZE_MESSAGE}",token:"${safe}",` +
    'height:h.scrollHeight},"*")}catch(e){}}' +
    "try{new ResizeObserver(r).observe(h)}catch(e){}" +
    'addEventListener("load",r);r()})();</script>'
  );
}

/**
 * The document the frame loads: the snippet as-is when it is a whole page
 * (CSP and theme stamp added to its head), otherwise wrapped in a minimal
 * page on the app's card surface so a bare `<div>` or `<svg>` reads in both
 * palettes. With `scripts: false` (the inert preview) no size reporter is
 * injected, since the frame would refuse to run it anyway. Exported for the tests.
 */
export function wrapInlineHtml(
  html: string,
  theme: Theme,
  token: string,
  { scripts = true }: { scripts?: boolean } = {},
): string {
  const script = scripts ? reporterScript(token) : "";
  if (/<html[\s>]/i.test(html)) {
    let doc = html;
    if (!/<html[^>]*\sdata-theme=/i.test(doc)) {
      doc = doc.replace(/<html(\s[^>]*)?>/i, (_m, attrs: string | undefined) =>
        `<html${attrs ?? ""} data-theme="${theme}">`,
      );
    }
    if (/<head[^>]*>/i.test(doc)) {
      doc = doc.replace(/<head[^>]*>/i, (m) => `${m}${headBits()}`);
    } else {
      doc = doc.replace(/<html[^>]*>/i, (m) => `${m}<head>${headBits()}</head>`);
    }
    return /<\/body>/i.test(doc)
      ? doc.replace(/<\/body>/i, `${script}</body>`)
      : `${doc}${script}`;
  }
  const skin = FRAGMENT_SKIN[theme];
  return (
    `<!doctype html><html lang="en" data-theme="${theme}"><head>${headBits()}` +
    `<style>:root{color-scheme:${theme}}html,body{margin:0}` +
    `body{padding:12px;background:${skin.bg};color:${skin.ink};` +
    'font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}' +
    "svg,img,canvas,video{max-width:100%}</style></head>" +
    `<body>${html}${script}</body></html>`
  );
}

/** An SVG snippet as an inert picture. */
export function svgDataUrl(svg: string): string {
  // Inline HTML supplies this namespace implicitly; an SVG image document does not.
  const document = svg.replace(/<svg(?=[\s>])[^>]*>/, root =>
    /\sxmlns\s*=/.test(root) ? root : root.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"'),
  );
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(document)}`;
}

/**
 * The sandboxed frame an inline HTML snippet renders in. Inert unless
 * `scripts` is set (the reader clicked "Run scripts"); only a scripted frame
 * can report its content height, so an inert one keeps a fixed height.
 */
export function InlineHtmlFrame({
  html,
  title,
  scripts = false,
}: {
  html: string;
  title: string;
  scripts?: boolean;
}) {
  const theme = useThemeValue();
  const token = useId();
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(MIN_FRAME_PX * 2);

  useEffect(() => {
    if (!scripts) return;
    const onMessage = (event: MessageEvent) => {
      const frame = ref.current;
      if (!frame || event.source !== frame.contentWindow) return;
      const data: unknown = event.data;
      if (
        typeof data !== "object" ||
        data === null ||
        (data as { type?: unknown }).type !== INLINE_HTML_SIZE_MESSAGE ||
        (data as { token?: unknown }).token !== token.replace(/[^\w:-]/g, "")
      ) {
        return;
      }
      const reported = Number((data as { height?: unknown }).height);
      if (!Number.isFinite(reported)) return;
      setHeight(Math.min(MAX_FRAME_PX, Math.max(MIN_FRAME_PX, Math.ceil(reported) + 2)));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [token, scripts]);

  const doc = useMemo(
    () => wrapInlineHtml(html, theme, token, { scripts }),
    [html, theme, token, scripts],
  );

  return (
    <iframe
      ref={ref}
      key={`${theme}-${scripts ? "scripts" : "inert"}`}
      title={title}
      srcDoc={doc}
      sandbox={scripts ? "allow-scripts" : ""}
      referrerPolicy="no-referrer"
      style={{ height: scripts ? height : INERT_FRAME_PX }}
      data-scripts={scripts ? "on" : "off"}
      className="block w-full border-0 bg-transparent"
      data-testid="inline-html-frame"
    />
  );
}

export function RenderedFence({ language, code }: { language: FenceLanguage; code: string }) {
  const t = useT();
  const [mode, setMode] = useState<"rendered" | "source">("rendered");
  const [copied, setCopied] = useState(false);
  const [scripts, setScripts] = useState(false);

  const copy = () => {
    void robustCopy(code).then((ok) => {
      if (!ok) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  const segment = (value: "rendered" | "source", label: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      onClick={() => setMode(value)}
      className={cn(
        "rounded-sm px-2 py-0.5 text-micro font-medium transition-colors",
        mode === value
          ? "bg-background text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );

  return (
    <div
      className="not-prose my-4 overflow-hidden rounded-md border border-border bg-muted/40"
      data-testid="rendered-fence"
      data-language={language}
      data-mode={mode}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/40 bg-muted/20 px-3 py-1">
        <span className="text-micro uppercase tracking-wider text-muted-foreground">{language}</span>
        <div className="flex items-center gap-1.5">
          {language === "html" && !scripts && mode === "rendered" ? (
            <button
              type="button"
              onClick={() => setScripts(true)}
              className="rounded px-2 py-0.5 text-micro font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
              title={t("outputs_view.fence_run_scripts_hint")}
              data-testid="inline-html-run-scripts"
            >
              {t("outputs_view.fence_run_scripts")}
            </button>
          ) : null}
          <div role="group" className="inline-flex rounded border border-border/60 bg-muted/40 p-0.5">
            {segment("rendered", t("outputs_view.fence_rendered"))}
            {segment("source", t("outputs_view.fence_source"))}
          </div>
          <button
            type="button"
            onClick={copy}
            className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            title={t("docs_content.copy_code")}
            aria-label={copied ? t("docs_content.code_copied") : t("docs_content.copy_code")}
          >
            {copied ? (
              <Check className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            ) : (
              <Copy className="h-3 w-3" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
      {mode === "source" ? (
        <CodeBlock language={language} code={code} chrome={false} />
      ) : language === "svg" ? (
        <div className="flex justify-center bg-card p-4">
          <img src={svgDataUrl(code)} alt="SVG" className="max-w-full" data-testid="inline-svg" />
        </div>
      ) : (
        <InlineHtmlFrame html={code} title="HTML" scripts={scripts} />
      )}
    </div>
  );
}
