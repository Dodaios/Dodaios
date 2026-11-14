/**
 * "New" in the Nodes library: a short menu of the kinds, like "New" in an
 * office suite. A kind starts a blank node of that kind at once (the kind's
 * designed starter) and opens it, ready to be typed into; nothing has to be
 * described first. The last entry still lets the reader describe what they
 * want and have the assistant build it.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { ChevronDown, Loader2, Plus, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { NODE_TYPES, type NodeType } from "./nodeModel";
import { NODE_TYPE_LABEL_KEY, nodeHueStyle } from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";

export interface NewNodeMenuProps {
  /** The kind being made right now (its entry spins; the menu takes no other). */
  creating: NodeType | null;
  /** Start a blank node of this kind and open it. */
  onBlank: (type: NodeType) => void;
  /** Describe it instead: the dialog that hands a request to the assistant. */
  onDescribe: () => void;
  /** Which edge of the button the menu lines up with. */
  align?: "start" | "end";
  testId?: string;
  className?: string;
}

const ITEM_SELECTOR = "[role='menuitem']";

export function NewNodeMenu({
  creating,
  onBlank,
  onDescribe,
  align = "end",
  testId = "nodes-new",
  className,
}: NewNodeMenuProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) root.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close(true);
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    panel.current?.querySelector<HTMLButtonElement>(ITEM_SELECTOR)?.focus({ preventScroll: true });
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open, close]);

  const onPanelKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>(ITEM_SELECTOR) ?? []);
    if (!items.length) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  };

  const busy = creating !== null;

  return (
    <div
      ref={root}
      className={cn("relative", className)}
      onBlur={(event) => {
        // Tab out of the menu: it closes behind the reader.
        if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <Button
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={busy}
        onClick={() => setOpen((value) => !value)}
        data-testid={testId}
      >
        {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
        {t("nodes.new.button")}
        <ChevronDown aria-hidden className="-mr-0.5 opacity-60" />
      </Button>
      {open && (
        <div
          ref={panel}
          role="menu"
          aria-label={t("nodes.new.menu_label")}
          onKeyDown={onPanelKeyDown}
          // A press inside must not move the focus: a WebView that does not
          // focus a clicked button would blur the menu shut before the click.
          onMouseDown={(event) => event.preventDefault()}
          data-testid="nodes-new-menu"
          className={cn(
            "absolute top-full z-50 mt-2 w-72 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float",
            "animate-in fade-in-0 zoom-in-95 duration-fast motion-reduce:animate-none",
            align === "end" ? "right-0" : "left-0",
          )}
        >
          <p className="px-2.5 pb-1 pt-1.5 text-sm text-muted-foreground">{t("nodes.new.blank_heading")}</p>
          {NODE_TYPES.map((type) => (
            <MenuItem
              key={type}
              testId={`nodes-new-blank-${type}`}
              icon={
                <span
                  aria-hidden
                  style={nodeHueStyle(type)}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--node-hue)/0.14)] text-[hsl(var(--node-hue))]"
                >
                  <NodeTypeIcon type={type} className="h-4 w-4" />
                </span>
              }
              onChoose={() => {
                close(false);
                onBlank(type);
              }}
            >
              {t(NODE_TYPE_LABEL_KEY[type])}
            </MenuItem>
          ))}
          <div role="separator" className="mx-1 my-1 h-px bg-border" />
          <MenuItem
            testId="nodes-new-describe"
            icon={
              <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center text-muted-foreground">
                <Sparkles className="h-4 w-4" />
              </span>
            }
            onChoose={() => {
              close(false);
              onDescribe();
            }}
          >
            {t("nodes.new.describe")}
          </MenuItem>
        </div>
      )}
    </div>
  );
}

function MenuItem({
  onChoose,
  testId,
  icon,
  children,
}: {
  onChoose: () => void;
  testId: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onChoose}
      data-testid={testId}
      className={cn(
        "flex h-9 w-full items-center gap-2.5 rounded-md px-1.5 text-left text-base text-foreground transition-colors duration-fast",
        "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none",
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}
