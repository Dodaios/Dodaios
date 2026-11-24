import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { Clipboard, Copy, ExternalLink, Link2, Scissors, TextSelect } from "lucide-react";

import { useT } from "@/i18n";
import { hasEmbeddedDesktopBridge } from "@/lib/embeddedDesktop";
import { useEventStore } from "@/store/events";
import { robustCopy, robustPaste, robustPasteFiles } from "@/lib/clipboard";
import {
  collectContextActions,
  linkUnder,
  type ContextAction,
} from "@/lib/contextActions";
import { openExternalUrl } from "@/lib/openExternal";
import {
  capabilitiesFor,
  captureEditSnapshot,
  deleteSelection,
  pasteInto,
  restoreEditFocus,
  selectAll,
  type EditCapabilities,
  type EditSnapshot,
} from "@/lib/editActions";
import { cn } from "@/lib/utils";

/**
 * App-wide right-click menu offering Cut / Copy / Paste / Select all, plus the
 * entries of the area that was clicked (see `lib/contextActions.ts`) and, on a
 * link, Open link / Copy link address.
 *
 * Text fields and selected text get the engine's own menu instead (see
 * `wantsNativeTextMenu`): it carries the spelling suggestions this menu cannot
 * offer. This menu stays for the terminals and the rest of the app.
 *
 * The desktop shell embeds the UI in a WebView whose own context menu is
 * switched off, so without this component right-clicking does nothing at all —
 * anywhere in the app. That leaves mouse-driven pasting impossible, which is
 * how most people paste. Mounted once in the app shell so it covers every
 * view, including the Agentic IDE terminals.
 *
 * Shift+right-click is deliberately left alone: in a real browser that still
 * opens the native menu, keeping the developer escape hatch intact.
 */

const MENU_WIDTH = 210;
const VIEWPORT_MARGIN = 8;

interface MenuState {
  x: number;
  y: number;
  snapshot: EditSnapshot;
  caps: EditCapabilities;
  /** Area entries, one group per registered area, innermost first. */
  groups: ContextAction[][];
}

function hasEditEntry(caps: EditCapabilities): boolean {
  return caps.canCut || caps.canCopy || caps.canPaste || caps.canSelectAll;
}

export function EditContextMenu() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => setMenu(null), []);

  // Read through a ref so the document listener is installed once.
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    const onContextMenu = (event: MouseEvent) => {
      // Escape hatch: let the browser's own menu through. A component that
      // opened its own menu has already claimed the click.
      if (event.shiftKey || event.defaultPrevented) return;
      const snapshot = captureEditSnapshot(event.target);
      if (wantsNativeTextMenu(snapshot)) return;
      const caps = capabilitiesFor(snapshot);
      const target = event.target instanceof Element ? event.target : null;
      const groups = collectContextActions(target);
      const link = linkUnder(target);
      if (link) groups.unshift(linkActions(link, tRef.current));
      // Nothing useful to offer (e.g. a right-click on empty chrome with no
      // selection) — stay out of the way rather than show a dead menu.
      if (groups.length === 0 && !hasEditEntry(caps)) return;
      event.preventDefault();
      setMenu({ x: event.clientX, y: event.clientY, snapshot, caps, groups });
    };

    document.addEventListener("contextmenu", onContextMenu);
    return () => document.removeEventListener("contextmenu", onContextMenu);
  }, []);

  useEffect(() => {
    if (!menu) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) close();
    };
    // A scroll or a resize moves the anchor out from under the menu.
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    document.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [menu, close]);

  // Keep the menu inside the window: near the right or bottom edge it flips
  // back over the cursor instead of being clipped.
  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node || !menu) return;
    const { width, height } = node.getBoundingClientRect();
    const maxX = window.innerWidth - width - VIEWPORT_MARGIN;
    const maxY = window.innerHeight - height - VIEWPORT_MARGIN;
    node.style.left = `${Math.max(VIEWPORT_MARGIN, Math.min(menu.x, maxX))}px`;
    node.style.top = `${Math.max(VIEWPORT_MARGIN, Math.min(menu.y, maxY))}px`;
    node.style.visibility = "visible";
    // Focus the menu so Escape and the arrow keys work without a mouse.
    node.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
  }, [menu]);

  const run = useCallback(
    async (action: "cut" | "copy" | "paste" | "selectAll") => {
      if (!menu) return;
      const { snapshot } = menu;
      close();

      if (action === "selectAll") {
        selectAll(snapshot);
        return;
      }
      if (action === "copy" || action === "cut") {
        const copied = await robustCopy(snapshot.selectedText);
        if (!copied) {
          pushToast("error", t("edit_menu.copy_failed"));
          return;
        }
        if (action === "cut") deleteSelection(snapshot);
        return;
      }
      // Paste.
      if (snapshot.filePasteBridge) {
        const paths = await robustPasteFiles();
        if (paths && paths.length > 0) {
          restoreEditFocus(snapshot);
          snapshot.filePasteBridge.pastePaths(paths);
          return;
        }
      }
      const text = await robustPaste();
      if (text === null) {
        pushToast("error", t("edit_menu.paste_unavailable"));
        return;
      }
      if (!text) return; // nothing on the clipboard — not an error
      if (!pasteInto(snapshot, text)) {
        pushToast("error", t("edit_menu.paste_failed"));
      }
    },
    [menu, close, pushToast, t],
  );

  const runArea = useCallback(
    (action: ContextAction) => {
      close();
      void Promise.resolve()
        .then(() => action.run())
        .catch((error: unknown) => {
          console.warn(`Context menu entry "${action.id}" failed:`, error);
          pushToast("error", t("edit_menu.action_failed"));
        });
    },
    [close, pushToast, t],
  );

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>(
        "button:not([disabled])",
      ) ?? [],
    );
    if (!items.length) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = (current + step + items.length) % items.length;
    items[next]?.focus();
  };

  if (!menu) return null;
  const { caps, groups } = menu;
  const showEdit = hasEditEntry(caps);

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={t("edit_menu.label")}
      onKeyDown={onMenuKeyDown}
      // Positioned in the layout effect above, once its real size is known.
      style={{ width: MENU_WIDTH, visibility: "hidden" }}
      className="fixed z-[100] overflow-hidden rounded-md border border-border bg-background py-1"
    >
      {groups.map((group, index) => (
        <div key={index} role="group">
          {index > 0 && <MenuDivider />}
          {group.map((action) => (
            <MenuItem
              key={action.id}
              icon={action.icon}
              label={action.label}
              shortcut={action.shortcut}
              disabled={Boolean(action.disabled)}
              onSelect={() => runArea(action)}
            />
          ))}
        </div>
      ))}
      {showEdit && groups.length > 0 && <MenuDivider />}
      {showEdit && <>
      {menu.snapshot.kind !== "terminal" && <MenuItem
        icon={Scissors}
        label={t("edit_menu.cut")}
        shortcut="Ctrl+X"
        disabled={!caps.canCut}
        onSelect={() => void run("cut")}
      />}
      <MenuItem
        icon={Copy}
        label={t("edit_menu.copy")}
        shortcut="Ctrl+C"
        disabled={!caps.canCopy}
        onSelect={() => void run("copy")}
      />
      <MenuItem
        icon={Clipboard}
        label={t("edit_menu.paste")}
        shortcut="Ctrl+V"
        disabled={!caps.canPaste}
        onSelect={() => void run("paste")}
      />
      <MenuItem
        icon={TextSelect}
        label={t("edit_menu.select_all")}
        shortcut="Ctrl+A"
        disabled={!caps.canSelectAll}
        onSelect={() => void run("selectAll")}
      />
      </>}
    </div>
  );
}

/** Open link / Copy link address, for a right-click on a link anywhere. */
function linkActions(href: string, t: (key: string) => string): ContextAction[] {
  return [
    {
      id: "open-link",
      label: t("edit_menu.open_link"),
      icon: ExternalLink,
      run: async () => {
        if (!(await openExternalUrl(href))) throw new Error("no browser reached");
      },
    },
    {
      id: "copy-link",
      label: t("edit_menu.copy_link"),
      icon: Link2,
      run: async () => {
        if (!(await robustCopy(href))) throw new Error("clipboard refused the link");
      },
    },
  ];
}

function MenuDivider() {
  return <div role="separator" className="my-1 h-px bg-border" />;
}

/**
 * True when the right-click should open the engine's own text menu.
 *
 * That menu knows the spelling suggestions for the word under the cursor, so
 * it wins in every text field and on any selected text. Terminals keep this
 * menu: their text lives in a canvas the engine cannot see. Inside the desktop
 * window the native menu exists only when the shell turned it on for text
 * (`__DODAIOS_NATIVE_TEXT_MENU`); without that flag this menu stays, so a
 * right-click never ends in nothing.
 */
export function wantsNativeTextMenu(snapshot: EditSnapshot): boolean {
  if (snapshot.kind === "terminal") return false;
  const onText =
    (snapshot.kind === "field" && snapshot.editable) ||
    snapshot.selectedText.trim() !== "";
  if (!onText) return false;
  const flag = (window as unknown as { __DODAIOS_NATIVE_TEXT_MENU?: boolean })
    .__DODAIOS_NATIVE_TEXT_MENU;
  return Boolean(flag) || !hasEmbeddedDesktopBridge();
}

function MenuItem({
  icon: Icon,
  label,
  shortcut,
  disabled,
  onSelect,
}: {
  icon?: ContextAction["icon"];
  label: string;
  shortcut?: string;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      // Without this the click moves focus off the field before the action
      // runs, and the caret — the place the text has to land — is gone.
      onMouseDown={(e) => e.preventDefault()}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm",
        disabled
          ? "cursor-default text-muted-foreground/40"
          : "text-foreground hover:bg-primary/10 focus:bg-primary/10 focus:outline-none",
      )}
    >
      {Icon ? (
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : (
        <span className="h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      <span className="flex-1">{label}</span>
      <span className="text-micro tracking-wider text-muted-foreground">
        {shortcut}
      </span>
    </button>
  );
}
