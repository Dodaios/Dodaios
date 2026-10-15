import { lazy, Suspense, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";
import { useT } from "@/i18n";

const MonacoDiff = lazy(() => import("./MonacoDiff"));

export interface DiffSource {
  /** The tab title: "app.py (abc1234)". */
  title: string;
  path: string;
  load: () => Promise<{ before: string | null; after: string | null; binary: boolean }>;
}

/** A large read-only diff over the app, for a commit's file or a deleted file. */
export function DiffDialog({ source, onClose }: { source: DiffSource; onClose: () => void }) {
  const t = useT();
  const [state, setState] = useState<{ before: string; after: string; binary: boolean } | { error: string } | null>(null);
  useEffect(() => {
    let alive = true;
    setState(null);
    source
      .load()
      .then((answer) => alive && setState({ before: answer.before ?? "", after: answer.after ?? "", binary: answer.binary }))
      .catch((error: Error) => alive && setState({ error: error.message }));
    return () => {
      alive = false;
    };
  }, [source]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 z-[110] flex items-center justify-center bg-background/60 p-6"
      onPointerDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={source.title}
        data-testid="scm-diff-dialog"
        className="flex h-full max-h-[86vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-border bg-background shadow-float"
      >
        <header className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3">
          <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground">{source.title}</span>
          <button
            type="button"
            aria-label={t("ide_side_panel.git.scm.close")}
            data-testid="scm-diff-close"
            onClick={onClose}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="relative min-h-0 flex-1">
          {!state ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden />
            </div>
          ) : "error" in state ? (
            <p className="p-6 text-center text-xs text-destructive">{state.error}</p>
          ) : state.binary ? (
            <p className="p-6 text-center text-xs text-muted-foreground">{t("ide_side_panel.git.scm.binary")}</p>
          ) : (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden />
                </div>
              }
            >
              <MonacoDiff path={source.path} before={state.before} after={state.after} />
            </Suspense>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
