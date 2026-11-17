/**
 * A menu at the pointer (a right click on the slide), drawn in a portal above
 * everything. Closes on Escape, on a click outside and when an item is
 * picked; the arrow keys move between the items.
 */
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface ContextMenuProps {
  at: { x: number; y: number };
  label: string;
  onClose: () => void;
  children: ReactNode;
}

export function ContextMenu({ at, label, onClose, children }: ContextMenuProps) {
  const panel = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState(at);

  useLayoutEffect(() => {
    const el = panel.current;
    if (!el) return;
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    setPlace({
      x: Math.max(8, Math.min(at.x, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(at.y, window.innerHeight - height - 8)),
    });
  }, [at]);

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", onPointer, true);
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus());
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      cancelAnimationFrame(frame);
    };
  }, [onClose]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
    items[next]?.focus();
  };

  return createPortal(
    <div
      ref={panel}
      role="menu"
      aria-label={label}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest('[role="menuitem"]')) onClose();
      }}
      style={{ left: place.x, top: place.y }}
      className="fixed z-[100] min-w-[13rem] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float"
      data-node-editor-popover=""
      data-testid="slides-context-menu"
    >
      {children}
    </div>,
    document.body,
  );
}

export function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-border" />;
}
