import { lazy, Suspense, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Codicon } from "./Codicon";
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
      className="scm-portal fixed inset-0 z-[110] flex items-center justify-center p-6"
      style={{ background: "rgba(0, 0, 0, 0.3)" }}
      onPointerDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={source.title}
        data-testid="scm-diff-dialog"
        className="flex h-full max-h-[86vh] w-full max-w-6xl flex-col overflow-hidden rounded-[6px]"
        style={{ background: "var(--scm-bg)", color: "var(--scm-fg)", border: "1px solid var(--scm-menu-border)", boxShadow: "0 0 8px 2px rgba(0, 0, 0, 0.36)" }}
      >
        <header className="flex h-[35px] shrink-0 items-center gap-[6px] px-[10px]" style={{ borderBottom: "1px solid var(--scm-border)" }}>
          <span className="min-w-0 flex-1 truncate text-[13px]">{source.title}</span>
          <button
            type="button"
            aria-label={t("ide_side_panel.git.scm.close")}
            data-testid="scm-diff-close"
            onClick={onClose}
            className="scm-action"
          >
            <Codicon name="close" />
          </button>
        </header>
        <div className="relative min-h-0 flex-1">
          {!state ? (
            <div className="flex h-full items-center justify-center">
              <Codicon name="loading" spin />
            </div>
          ) : "error" in state ? (
            <p className="p-6 text-center text-[13px]" style={{ color: "var(--scm-deleted)" }}>{state.error}</p>
          ) : state.binary ? (
            <p className="p-6 text-center text-[13px] opacity-70">{t("ide_side_panel.git.scm.binary")}</p>
          ) : (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center">
                  <Codicon name="loading" spin />
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
