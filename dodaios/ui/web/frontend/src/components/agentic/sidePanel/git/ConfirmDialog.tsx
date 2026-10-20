import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * The question asked before anything that cannot be taken back: deleting a
 * branch, rewriting local commits. Cancel has the focus, so Enter never
 * confirms by accident; Escape and a click outside both cancel.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive = true,
  busy = false,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  body?: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const t = useT();
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => cancelButton.current?.focus(), []);
  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 z-[110] flex items-center justify-center bg-background/60 p-4"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !busy) {
          event.stopPropagation();
          onCancel();
        }
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="git-confirm-title"
        data-testid="git-confirm"
        className="w-full max-w-sm rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-float"
      >
        <h2 id="git-confirm-title" className="break-words text-sm font-semibold text-foreground">
          {title}
        </h2>
        {body && <p className="mt-1.5 whitespace-pre-line break-words text-xs leading-relaxed text-muted-foreground">{body}</p>}
        {children}
        <div className="mt-4 flex justify-end gap-2">
          <button
            ref={cancelButton}
            type="button"
            data-testid="git-confirm-cancel"
            disabled={busy}
            onClick={onCancel}
            className="h-8 rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            {t("ide_side_panel.git.confirm.cancel")}
          </button>
          <button
            type="button"
            data-testid="git-confirm-ok"
            disabled={busy}
            onClick={onConfirm}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
              destructive ? "bg-destructive text-destructive-foreground hover:opacity-90" : "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />}
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}
