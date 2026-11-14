/**
 * The node's real page for a spec that is not saved yet.
 *
 * An editor that wants to show exactly what the renderer will draw asks
 * `POST /api/nodes/{id}/preview` for the page and puts it in a frame here.
 * The frame is the same kind of sandbox the stage uses for a node's page
 * (`sandbox="allow-scripts"`, no same origin), and because a `srcdoc` page
 * gets no response headers, the network-shut policy of the node page route
 * is written into the document as a meta tag. The app's theme is stamped on
 * the page the way the stage's `?theme=` query does it.
 *
 * `useNodePreview` debounces the requests while the person types and drops
 * answers that arrive after a newer spec was asked for.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { useThemeValue } from "@/hooks/useTheme";
import { fetchNodePreview } from "./api";
import { NodesApiError } from "../useNodes";

/** The node page route's policy, minus `sandbox` (which a meta tag cannot carry). */
export const PREVIEW_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; " +
  "font-src data:; media-src data: blob:; connect-src 'none'; form-action 'none'; frame-src 'none'; base-uri 'none';";

/** `html` with the policy, the theme and an optional script of the editor's own. */
export function preparePreviewHtml(html: string, theme: string, script?: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`;
  const extra = script ? `<script>${script.replace(/<\/script/gi, "<\\/script")}</script>` : "";
  let out = html;
  // The policy must come before anything it governs: first thing in <head>.
  if (/<head[^>]*>/i.test(out)) out = out.replace(/<head[^>]*>/i, (head) => `${head}${meta}`);
  else out = `${meta}${out}`;
  if (theme === "light" || theme === "dark") {
    out = /<html[^>]*>/i.test(out)
      ? out.replace(/<html([^>]*)>/i, (_m, attrs: string) => `<html${attrs.replace(/\sdata-theme="[^"]*"/i, "")} data-theme="${theme}">`)
      : out;
  }
  if (extra) out = /<\/body>/i.test(out) ? out.replace(/<\/body>/i, `${extra}</body>`) : `${out}${extra}`;
  return out;
}

export interface PreviewFrameProps {
  /** The page from `fetchNodePreview`; null draws an empty frame. */
  html: string | null;
  title: string;
  /** A script of the editor's own, run inside the page (e.g. a picker). */
  script?: string;
  /** Messages the page posts to the app, only from this frame. */
  onMessage?: (data: unknown) => void;
  className?: string;
}

export function PreviewFrame({ html, title, script, onMessage, className }: PreviewFrameProps) {
  const theme = useThemeValue();
  const frame = useRef<HTMLIFrameElement>(null);
  const doc = useMemo(() => (html === null ? "" : preparePreviewHtml(html, theme, script)), [html, theme, script]);
  const listener = useRef(onMessage);
  listener.current = onMessage;
  useEffect(() => {
    const onWindowMessage = (event: MessageEvent) => {
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      listener.current?.(event.data);
    };
    window.addEventListener("message", onWindowMessage);
    return () => window.removeEventListener("message", onWindowMessage);
  }, []);
  return (
    <iframe
      ref={frame}
      title={title}
      srcDoc={doc}
      sandbox="allow-scripts"
      data-testid="node-preview-frame"
      className={className ?? "h-full w-full border-0 bg-background"}
    />
  );
}

export interface NodePreview {
  html: string | null;
  loading: boolean;
  /** The server's reason when the spec could not be drawn; "" otherwise. */
  error: string;
}

/** The page for `spec`, asked for `delayMs` after the spec stops changing. */
export function useNodePreview(nodeId: string, spec: unknown, options: { delayMs?: number; enabled?: boolean } = {}): NodePreview {
  const delay = options.delayMs ?? 400;
  const enabled = options.enabled ?? true;
  const [state, setState] = useState<NodePreview>({ html: null, loading: enabled, error: "" });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState((now) => ({ ...now, loading: true }));
    const timer = window.setTimeout(() => {
      fetchNodePreview(nodeId, spec, controller.signal)
        .then((html) => setState({ html, loading: false, error: "" }))
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          const reason = error instanceof NodesApiError ? error.detail || error.message : String(error);
          // Keep the last good page on screen; say why this one is missing.
          setState((now) => ({ html: now.html, loading: false, error: reason }));
        });
    }, delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [nodeId, spec, delay, enabled]);
  return state;
}
