import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, X } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/**
 * The compact card an agent puts in the chat when the person has to do one
 * thing: sign in, connect a service. A tile (logo or key), a title, one quiet
 * line and one button. Settled, it keeps the tile and says what happened.
 */
export function ChatPromptCard({
  testId,
  tile,
  title,
  subtitle,
  action,
  settled,
  className,
}: {
  testId: string;
  tile: ReactNode;
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  settled?: { tone: "success" | "muted"; label: string };
  className?: string;
}) {
  return (
    <div
      data-testid={testId}
      data-state={settled ? settled.tone : "open"}
      className={cn(
        "my-2 flex w-full max-w-md items-center gap-3 rounded-2xl border border-border bg-card px-3.5 py-3",
        className,
      )}
    >
      <div className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-background text-muted-foreground">
        {tile}
      </div>
      <div className="min-w-0 flex-1">
        <p className="m-0 truncate text-sm font-medium text-foreground">{title}</p>
        {settled ? (
          <p
            className={cn(
              "m-0 flex items-center gap-1 truncate text-xs",
              settled.tone === "success" ? "text-emerald-500" : "text-muted-foreground",
            )}
          >
            {settled.tone === "success" ? <Check aria-hidden className="h-3.5 w-3.5 shrink-0" /> : null}
            <span className="truncate">{settled.label}</span>
          </p>
        ) : subtitle ? (
          <p className="m-0 truncate text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      {settled ? null : action}
    </div>
  );
}

/** The card's one button: a pill in the text colour, the one thing to press. */
export function ChatPromptButton({
  children,
  onClick,
  disabled,
  testId,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="shrink-0 rounded-full bg-foreground px-4 py-1.5 text-sm font-medium text-background transition-colors hover:bg-foreground/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
    >
      {children}
    </button>
  );
}

/** A small centred popup over the chat; Escape or the backdrop closes it. */
export function ChatPopup({
  title,
  tile,
  onClose,
  children,
  testId,
}: {
  title: string;
  tile?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const t = useT();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("input, button[type=submit]")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div
      className="fixed inset-0 z-[80] grid place-items-center bg-black/50 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
        className="w-full max-w-sm rounded-2xl border border-border bg-card p-5 text-foreground shadow-2xl"
      >
        <div className="mb-4 flex items-center gap-3">
          {tile ? (
            <div className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-background text-muted-foreground">
              {tile}
            </div>
          ) : null}
          <h2 id={titleId} className="m-0 min-w-0 flex-1 truncate text-base font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("login_card.close")}
            className="grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-muted"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
