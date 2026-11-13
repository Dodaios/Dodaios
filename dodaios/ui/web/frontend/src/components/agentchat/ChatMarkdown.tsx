import { Children, createContext, lazy, Suspense, useContext, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { translate } from "@/i18n";
import { cn } from "@/lib/utils";
import { openExternalUrl } from "@/lib/openExternal";
import { openLocalPath } from "@/lib/openLocalPath";
import { readFence, visualFenceLanguage } from "@/lib/visualFence";
import { CHART_FENCE, endsInOpenFence, parseChartSpec } from "@/lib/chartSpec";
import { chatLinkAction, chatUrlTransform, localPathFromChatHref, pageRefFromChatHref, threadRefFromChatHref } from "./chatLinks";
import { PageLink } from "./PageCard";
import { WebLink } from "./WebLink";
import { webLinkInfo } from "./webLinks";
import { CodingAgentLink } from "@/components/agentic/threads/CodingAgentLink";
import { parseToolResult, ToolResultCard } from "./ToolResultCard";
import { CodeBlock } from "@/components/docs/CodeBlock";
import { MediaPreview, mediaKind, safeMediaUrl } from "./MediaPreview";

export { MediaPreview, mediaKind, safeMediaUrl } from "./MediaPreview";
export type { MediaKind } from "./MediaPreview";

const RenderedFence = lazy(() => import("@/components/outputs/RenderedFence").then(module => ({ default: module.RenderedFence })));
// The chart library is large and most answers carry no chart, so it loads with the first one.
const ChartFence = lazy(() => import("@/components/outputs/ChartFence").then(module => ({ default: module.ChartFence })));
const ChartFencePending = lazy(() => import("@/components/outputs/ChartFence").then(module => ({ default: module.ChartFencePending })));

function assetKey(raw: string): string {
  try {
    const url = new URL(raw, "http://chat.local");
    url.hash = "";
    if (url.pathname.startsWith("/api/outputs/")) url.searchParams.delete("disposition");
    return url.href;
  } catch { return raw; }
}

/** Recognize media tags without executing arbitrary model-authored HTML. */
export function normalizeMediaMarkup(text: string): string {
  const attr = (markup: string, name: string) => markup.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i"))?.[1];
  // Protect CommonMark fences, including tilde fences and a still-streaming
  // block. Rewriting an <img> inside HTML code corrupts the eventual preview.
  const parts: string[] = [""];
  let fence: string | null = null;
  for (const line of text.match(/[^\n]*\n|[^\n]+$/g) ?? []) {
    const marker = /^ {0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$/.exec(line);
    if (!fence && marker && !(marker[1][0] === "`" && marker[2].includes("`"))) {
      fence = marker[1];
      parts.push(line);
    } else if (fence) {
      parts[parts.length - 1] += line;
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) {
        fence = null;
        parts.push("");
      }
    } else {
      parts[parts.length - 1] += line;
    }
  }
  return parts.map((part, i) => i % 2 ? part : part
    .replace(/<(video|audio)\b([^>]*)>([\s\S]*?)<\/\1>/gi, (original, kind: string, head: string, body: string) => {
      const source = attr(head, "src") ?? attr(body.match(/<source\b[^>]*>/i)?.[0] ?? "", "src");
      if (!source || !safeMediaUrl(source)) return original;
      const marker = source.includes("#") ? "&" : "#";
      return `\n\n[${kind}](<${source}${marker}jarvis-media=${kind}%2F${kind === "video" ? "mp4" : "mpeg"}>)\n\n`;
    })
    .replace(/<img\b[^>]*>/gi, original => {
      const src = attr(original, "src");
      if (!src || !safeMediaUrl(src)) return original;
      const alt = (attr(original, "alt") ?? "image").replace(/[\[\]\r\n]/g, " ");
      return `![${alt}](<${src}>)`;
    })).join("");
}

const ImageKeysContext = createContext<ReadonlySet<string>>(new Set());
/** Whether the text ends inside a fence, i.e. its last block is still being written. */
const OpenFenceContext = createContext(false);

/**
 * A fenced `chart` block as the chart it describes. While the block is still
 * arriving its place is held by a chart-shaped wait, so the reader never
 * watches JSON scroll by; a finished block that is not a drawable chart stays
 * the code it is.
 */
function ChartBlock({ code }: { code: string }) {
  const writing = useContext(OpenFenceContext);
  const spec = useMemo(() => parseChartSpec(code), [code]);
  if (spec) return <Suspense fallback={null}><ChartFence spec={spec} /></Suspense>;
  if (writing) return <Suspense fallback={null}><ChartFencePending /></Suspense>;
  return <CodeBlock language="json" code={code} dense />;
}

// A file or folder address must not be loaded in this window: an empty href
// reloads the page, and a relative name is served back as the app itself.
function onChatLinkClick(event: { preventDefault(): void }, href: string, label = "") {
  const action = chatLinkAction(href, label);
  if (action.type === "allow") return;
  event.preventDefault();
  if (action.type === "local") void openLocalPath(action.path);
  else if (action.type === "external") void openExternalUrl(action.url);
}

// Stable component identities are essential: changing these on each streamed
// token would unmount videos, reset playback and discard image error state.
const MARKDOWN_COMPONENTS: Components = {
  img: ({ src = "", alt = translate("chat_media.image_fallback") }) => {
    const local = localPathFromChatHref(src);
    if (local) return <a href={src} title={local} onClick={event => onChatLinkClick(event, src, alt || local)}>{alt || local}</a>;
    return <MediaPreview src={src} label={alt || translate("chat_media.image_fallback")} kind={mediaKind(src) ?? "image"} />;
  },
  a: function MediaLink({ href = "", children }) {
    const imageKeys = useContext(ImageKeysContext);
    const kind = mediaKind(href);
    const label = Children.toArray(children).filter(child => typeof child === "string").join("") || kind || "media";
    if (kind && !imageKeys.has(assetKey(href))) return <MediaPreview src={href} label={label} kind={kind} />;
    // A coding agent the answer points at: its title and logo, opening its thread.
    const thread = threadRefFromChatHref(href);
    if (thread) {
      // The answer's own words stay: the link is part of its sentence.
      const written = Children.toArray(children).filter(child => typeof child === "string").join("");
      return <CodingAgentLink threadRef={thread} label={written} words={written} />;
    }
    // A page in the Artifacts section: its name with the page mark, opening it there.
    const page = pageRefFromChatHref(href);
    if (page) return <PageLink pageRef={page} label={Children.toArray(children).filter(child => typeof child === "string").join("")} />;
    const local = localPathFromChatHref(href);
    // A web page: its site's logo and a short name; the full address is on the hover card.
    const web = local ? null : webLinkInfo(href, Children.toArray(children).every(child => typeof child === "string") ? label : null);
    if (web) return <WebLink info={web} onOpen={event => onChatLinkClick(event, href, label)}>{children}</WebLink>;
    return <a href={href} title={local || undefined} onClick={event => onChatLinkClick(event, href, label)}>{children}</a>;
  },
  pre: ({ children, node: _node, ...props }) => {
    const fence = readFence(children);
    if (fence) {
      if (fence.language === CHART_FENCE) return <ChartBlock code={fence.code} />;
      if (fence.language === "json" || fence.language === "") {
        const result = parseToolResult(fence.code);
        if (result) return <ToolResultCard result={result} code={fence.code} />;
      }
      const language = visualFenceLanguage(fence.language, fence.code);
      if (language) return <Suspense fallback={<pre>{children}</pre>}><RenderedFence language={language} code={fence.code} /></Suspense>;
      // Any other fenced code: its language on top, a copy button, highlighting.
      return <CodeBlock language={fence.language} code={fence.code} dense />;
    }
    return <pre {...props}>{children}</pre>;
  },
};

export function ChatMarkdown({ text, className }: { text: string; className?: string }) {
  const body = useMemo(() => normalizeMediaMarkup(text), [text]);
  const imageKeys = useMemo(() => new Set(Array.from(body.matchAll(/!\[[^\]]*\]\(<?([^)>]+)>?\)/g), match => assetKey(match[1]))), [body]);
  const writing = useMemo(() => body.includes(CHART_FENCE) && endsInOpenFence(body), [body]);
  return <div className={cn("min-w-0 [overflow-wrap:anywhere]", className)}>
    <ImageKeysContext.Provider value={imageKeys}>
      <OpenFenceContext.Provider value={writing}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={url => url.startsWith("data:") ? safeMediaUrl(url) ?? "" : chatUrlTransform(url)} components={MARKDOWN_COMPONENTS}>{body}</ReactMarkdown>
      </OpenFenceContext.Provider>
    </ImageKeysContext.Provider>
  </div>;
}
