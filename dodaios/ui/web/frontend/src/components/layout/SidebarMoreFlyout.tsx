import { MoreHorizontal } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import type { NavItem } from "@/components/layout/navGroups";

/**
 * "More" opens a panel BESIDE the sidebar instead of pushing the rest of the
 * column down (maintainer request 2026-10-26). The panel lives in a portal on
 * <body>, fixed to the viewport, so the sidebar's own scroller cannot clip it;
 * z-[70] is the app's floating level (see DockRail's label).
 *
 * It closes on a pick, a click outside, Escape, or a second click on "More".
 */
export function SidebarMoreFlyout({
  items,
  railed,
  rowClass,
  label,
  renderRow,
}: {
  items: NavItem[];
  railed: boolean;
  rowClass: string;
  label: string;
  renderRow: (item: NavItem) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const place = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const panelHeight = panelRef.current?.offsetHeight ?? 0;
    // Open level with the button; lift it when it would run off the bottom.
    const maxTop = window.innerHeight - panelHeight - 8;
    setPos({ top: Math.max(8, Math.min(rect.top, maxTop)), left: rect.right + 8 });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => { setOpen((v) => !v); }}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls="sidebar-more"
        title={label}
        data-testid="sidebar-more-toggle"
        className={cn(rowClass, "text-muted-foreground", open && "bg-secondary text-foreground")}
      >
        <MoreHorizontal aria-hidden strokeWidth={1.75} className="h-[18px] w-[18px] shrink-0" />
        {!railed && <span>{label}</span>}
      </button>
      {open &&
        createPortal(
          <div
            ref={panelRef}
            id="sidebar-more"
            role="menu"
            aria-label={label}
            data-testid="sidebar-more-panel"
            style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
            // A pick closes the panel; the row's own handler opens the section.
            onClick={(event) => {
              if ((event.target as HTMLElement).closest("button")) setOpen(false);
            }}
            className="fixed z-[70] max-h-[calc(100vh-16px)] w-60 overflow-y-auto rounded-xl border border-border bg-popover p-1.5 shadow-float scrollbar-jarvis"
          >
            <ul className="space-y-px">{items.map((item) => renderRow(item))}</ul>
          </div>,
          document.body,
        )}
    </>
  );
}
