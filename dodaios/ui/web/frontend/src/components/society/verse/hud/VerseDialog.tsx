/**
 * The frame the HUD's dialogs share (turbolift, launcher, simulator): a real
 * modal on Radix Dialog, drawn in place inside the stage so it keeps the ship
 * display look. Focus stays inside while it is open, Escape or a press on the
 * scrim closes it, and focus goes back to whatever had it before.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type ReactNode, type RefObject } from "react";

/**
 * Puts focus back on the element that held it when the caller mounted, once
 * the caller unmounts and focus went with it. Focus that something else took
 * in the meantime (a game that opened in the dialog's place) is left alone.
 */
export function useReturnFocus(active = true): void {
  const [opener] = useState(() => (typeof document === "undefined" ? null : document.activeElement));
  useEffect(() => {
    if (!active) return;
    return () => {
      window.setTimeout(() => {
        const now = document.activeElement;
        if (now && now !== document.body) return;
        if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
      }, 0);
    };
  }, [active, opener]);
}

interface Props {
  title: string;
  closeLabel: string;
  onClose: () => void;
  /** Extra classes beside `verse-dialog`. */
  className?: string;
  /** Where focus lands on open; the first control otherwise. */
  initialFocus?: RefObject<HTMLElement | null>;
  /** False when the caller outlives the dialog and puts focus back itself. */
  returnFocus?: boolean;
  children: ReactNode;
}

export function VerseDialog({ title, closeLabel, onClose, className, initialFocus, returnFocus = true, children }: Props) {
  useReturnFocus(returnFocus);
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Overlay className="verse-scrim">
        <Dialog.Content
          className={className ? `verse-dialog ${className}` : "verse-dialog"}
          aria-modal="true"
          aria-describedby={undefined}
          onOpenAutoFocus={(e) => {
            const target = initialFocus?.current;
            if (target) { e.preventDefault(); target.focus(); }
          }}
          // useReturnFocus puts the opener back; Radix would aim at a trigger these dialogs do not have.
          onCloseAutoFocus={(e) => e.preventDefault()}
          // Escape closes the dialog only, not the stage's selection behind it.
          onEscapeKeyDown={(e) => e.stopPropagation()}
        >
          <header className="verse-dialog-head">
            <Dialog.Title asChild>
              <span className="verse-dialog-title">{title}</span>
            </Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="verse-close" aria-label={closeLabel}>
                <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.2" /></svg>
              </button>
            </Dialog.Close>
          </header>
          {children}
        </Dialog.Content>
      </Dialog.Overlay>
    </Dialog.Root>
  );
}
