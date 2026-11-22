/**
 * A self-contained HTML file an answer shows, drawn where the answer names it.
 *
 * The chat stored the file when the answer arrived (`dodaios/agent_chat/media.py`),
 * so the page reads as it was then. Its text is fetched and drawn in the
 * visual frame: a sandboxed document that reaches no network and runs the
 * page's scripts only when the reader asks. The file's address is never
 * loaded as a page of the app.
 */
import { useEffect, useState } from "react";
import { AlertCircle, Download } from "lucide-react";

import { useT } from "@/i18n";
import { RenderedFence, RenderedFencePending } from "./RenderedFence";

/** A page larger than this is no figure in a conversation; its link still opens it. */
export const MAX_PAGE_CHARS = 2_000_000;

type Loaded = { src: string; text: string | null };

export function PagePreview({ src, label }: { src: string; label: string }) {
  const t = useT();
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(src)
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then((text) => { if (alive) setLoaded({ src, text: text.length <= MAX_PAGE_CHARS ? text : null }); })
      .catch(() => { if (alive) setLoaded({ src, text: null }); });
    return () => { alive = false; };
  }, [src]);

  if (!loaded || loaded.src !== src) return <RenderedFencePending />;
  if (loaded.text === null) {
    return <span role="status" className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
      <AlertCircle aria-hidden className="h-4 w-4 shrink-0" />{t("chat_media.unavailable")}
    </span>;
  }
  return <RenderedFence language="html" code={loaded.text} title={label} action={
    <a href={src} download title={t("chat_media.download")} aria-label={`${t("chat_media.download")} · ${label}`} data-testid="page-download"
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Download aria-hidden className="h-3.5 w-3.5" />
    </a>
  } />;
}
