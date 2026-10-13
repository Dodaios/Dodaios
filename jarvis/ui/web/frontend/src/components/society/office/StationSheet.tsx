/**
 * What opens from a station. A station that manages something (teams, the
 * directory, a launcher) opens a dialog built like every other dialog of the
 * app: the same scrim, surface, header and type scale. A station whose effect
 * shows in the world (the wardrobe) opens a panel docked at the side instead,
 * so the person keeps seeing — and walking — their character.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

const closeButton = "inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const WIDTH = {
  md: "w-[min(32rem,calc(100vw-2rem))]",
  lg: "w-[min(42rem,calc(100vw-2rem))]",
} as const;

export function StationSheet({ title, description, size = "lg", onClose, returnFocus, children }: {
  title: string; description?: string; size?: keyof typeof WIDTH; onClose: () => void;
  /**
   * Where focus goes when the dialog has closed (the map's canvas host, so the walking keys answer at once).
   * Without it focus returns to whatever had it before the dialog opened.
   */
  returnFocus?: () => void;
  children: ReactNode;
}) {
  const t = useT();
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[150] bg-scrim/60 backdrop-blur-sm" />
        <Dialog.Content data-office-ui {...(description ? {} : { "aria-describedby": undefined })}
          onCloseAutoFocus={(event) => {
            if (!returnFocus) return;
            event.preventDefault();
            returnFocus();
          }}
          className={cn("fixed left-1/2 top-1/2 z-[151] flex max-h-[90dvh] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-background text-foreground shadow-xl", WIDTH[size])}>
          <div className="flex items-start justify-between gap-4 border-b border-border p-5">
            <div className="grid min-w-0 gap-1.5">
              <Dialog.Title className="font-display text-lg font-semibold">{title}</Dialog.Title>
              {description && <Dialog.Description className="text-sm text-muted-foreground">{description}</Dialog.Description>}
            </div>
            <Dialog.Close className={closeButton} aria-label={t("society.office.close")}><X size={16} aria-hidden /></Dialog.Close>
          </div>
          <div className="grid gap-5 overflow-y-auto p-5">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The docked variant: a panel in the stage's side slot. Not modal; Escape (handled by the stage) closes it. */
export function StationSidePanel({ title, description, onClose, children }: {
  title: string; description?: string; onClose: () => void; children: ReactNode;
}) {
  const t = useT();
  const headingId = useId();
  const panel = useRef<HTMLElement>(null);
  // Focus moves into the fresh panel so keyboard and screen-reader users land on it;
  // the walking keys keep working because they listen on the window.
  useEffect(() => { panel.current?.focus({ preventScroll: true }); }, []);
  return (
    <aside ref={panel} className="office-card office-panel" data-office-ui aria-labelledby={headingId} tabIndex={-1}>
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="grid min-w-0 gap-0.5">
          <h2 id={headingId} className="font-display text-base font-semibold">{title}</h2>
          {description && <p className="text-xs text-muted-foreground">{description}</p>}
        </div>
        <button type="button" className={closeButton} onClick={onClose} aria-label={t("society.office.close")}><X size={16} aria-hidden /></button>
      </header>
      <div className="office-panel-body">{children}</div>
    </aside>
  );
}
