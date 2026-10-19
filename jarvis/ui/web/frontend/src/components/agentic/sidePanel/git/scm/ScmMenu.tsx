import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Codicon } from "./Codicon";

export type MenuItem =
  | {
      kind?: "item";
      id: string;
      label: string;
      /** Shown dimmed at the right edge ("Ctrl+Enter"). */
      hint?: string;
      disabled?: boolean;
      checked?: boolean;
      run: () => void;
    }
  | { kind: "submenu"; id: string; label: string; disabled?: boolean; items: MenuItem[] }
  | { kind: "separator"; id: string };

const MENU_WIDTH = 236;
const ITEM_HEIGHT = 24;

function isActionable(item: MenuItem): boolean {
  return item.kind !== "separator" && !item.disabled;
}

function MenuPanel({
  items,
  x,
  y,
  level,
  testId,
  onClose,
  onBack,
}: {
  items: MenuItem[];
  x: number;
  y: number;
  level: number;
  testId: string;
  onClose: () => void;
  /** Closes this submenu and gives the keyboard back to its parent. */
  onBack?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: x, top: y });
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState<{ index: number; x: number; y: number; keyboard: boolean } | null>(null);

  // Keep the whole menu on screen: flip left of the anchor, lift above the bottom edge.
  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const width = box.width || MENU_WIDTH;
    const left = x + width > window.innerWidth - 4 ? Math.max(4, (level > 0 ? x - width - MENU_WIDTH + 8 : window.innerWidth - width - 4)) : x;
    const top = y + box.height > window.innerHeight - 4 ? Math.max(4, window.innerHeight - box.height - 4) : y;
    setPosition({ left, top });
  }, [x, y, level, items.length]);

  useEffect(() => {
    if (level > 0 && active >= 0) ref.current?.focus();
  }, [level, active]);
  useEffect(() => {
    ref.current?.focus();
  }, []);

  const openSubmenu = (index: number, keyboard: boolean) => {
    const element = ref.current?.querySelector<HTMLElement>(`[data-menu-index="${index}"]`);
    const box = element?.getBoundingClientRect();
    if (!box) return;
    setOpen({ index, x: box.right - 2, y: box.top - 4, keyboard });
  };

  const move = (step: number) => {
    if (!items.some(isActionable)) return;
    let next = active;
    do {
      next = (next + step + items.length) % items.length;
    } while (!isActionable(items[next]));
    setActive(next);
  };

  const activate = (index: number, keyboard: boolean) => {
    const item = items[index];
    if (!item || !isActionable(item)) return;
    if (item.kind === "submenu") return openSubmenu(index, keyboard);
    if (item.kind === "separator") return;
    onClose();
    item.run();
  };

  return (
    <>
      <div
        ref={ref}
        role="menu"
        tabIndex={-1}
        data-testid={testId}
        className="scm-portal fixed z-[120] max-w-[320px] rounded-[5px] py-[4px] outline-none"
        style={{ left: position.left, top: position.top, minWidth: MENU_WIDTH, background: "var(--scm-menu-bg)", color: "var(--scm-menu-fg)", border: "1px solid var(--scm-menu-border)", boxShadow: "0 2px 8px rgba(0, 0, 0, 0.36)" }}
        onContextMenu={(event) => event.preventDefault()}
        onKeyDown={(event) => {
          if (open) return;
          if (event.key === "ArrowDown") move(1);
          else if (event.key === "ArrowUp") move(-1);
          else if (event.key === "Enter" || event.key === " ") activate(active, true);
          else if (event.key === "ArrowRight" && items[active]?.kind === "submenu") openSubmenu(active, true);
          else if (event.key === "ArrowLeft" && onBack) onBack();
          else if (event.key === "Escape") (onBack ?? onClose)();
          else return;
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        {items.map((item, index) =>
          item.kind === "separator" ? (
            <div key={item.id} role="separator" className="mx-[10px] my-[4px] h-px" style={{ background: "var(--scm-menu-separator)" }} />
          ) : (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              data-menu-index={index}
              data-testid={`scm-menu-${item.id}`}
              disabled={item.disabled}
              aria-haspopup={item.kind === "submenu" || undefined}
              onMouseEnter={() => {
                setActive(index);
                if (item.kind === "submenu" && !item.disabled) openSubmenu(index, false);
                else setOpen(null);
              }}
              onClick={() => activate(index, false)}
              style={{ height: ITEM_HEIGHT, ...(active === index && !item.disabled ? { background: "var(--scm-menu-selection)", color: "var(--scm-menu-selection-fg)" } : {}) }}
              className="mx-[4px] flex w-[calc(100%-8px)] items-center rounded-[3px] pr-[8px] text-left disabled:opacity-40"
            >
              <span className="flex w-[26px] shrink-0 justify-center">{item.kind !== "submenu" && item.checked && <Codicon name="check" />}</span>
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              {item.kind === "submenu" ? (
                <Codicon name="chevron-right" className="shrink-0" />
              ) : (
                item.hint && <span className="shrink-0 pl-[2em]">{item.hint}</span>
              )}
            </button>
          ),
        )}
      </div>
      {open && items[open.index]?.kind === "submenu" && (
        <MenuPanel
          key={open.index}
          items={(items[open.index] as { items: MenuItem[] }).items}
          x={open.x}
          y={open.y}
          level={level + 1}
          testId={`${testId}-sub`}
          onClose={onClose}
          onBack={() => {
            setOpen(null);
            ref.current?.focus();
          }}
        />
      )}
    </>
  );
}

/** A menu at a screen point, with submenus; closes on Escape, a click outside or a choice. */
export function ScmMenu({ items, x, y, onClose, testId = "scm-menu" }: { items: MenuItem[]; x: number; y: number; onClose: () => void; testId?: string }) {
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!(event.target as HTMLElement | null)?.closest?.("[role=menu]")) onClose();
    };
    const blur = () => onClose();
    window.addEventListener("pointerdown", close, true);
    window.addEventListener("blur", blur);
    window.addEventListener("resize", blur);
    return () => {
      window.removeEventListener("pointerdown", close, true);
      window.removeEventListener("blur", blur);
      window.removeEventListener("resize", blur);
    };
  }, [onClose]);
  return createPortal(<MenuPanel items={items} x={x} y={y} level={0} testId={testId} onClose={onClose} />, document.body);
}

/** Where a menu opened from a button should appear: under its bottom edge, right-aligned. */
export function menuPointFor(element: HTMLElement): { x: number; y: number } {
  const box = element.getBoundingClientRect();
  return { x: Math.max(4, box.right - MENU_WIDTH), y: box.bottom + 2 };
}

export function MenuHost({ menu, onClose }: { menu: { items: MenuItem[]; x: number; y: number } | null; onClose: () => void }): ReactNode {
  return menu ? <ScmMenu items={menu.items} x={menu.x} y={menu.y} onClose={onClose} /> : null;
}
