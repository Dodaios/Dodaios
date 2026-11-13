/**
 * What can be done to a card of the Nodes library: the menu behind its
 * "more" button and its right-click, and everything the menu's items lead to
 * (the rename dialog, the delete question, the toasts).
 *
 * The desktop WebView has no native context menu and the app has no menu
 * primitive, so the menu is drawn here: a portal with `role="menu"`, arrow
 * keys between the items, Escape to leave, focus handed back to where it
 * came from. What it offers follows the card:
 *
 *   every card      Open, Add to / Remove from favorites, Delete…
 *   a typed node    Rename…, Duplicate, Ask the assistant to change it…,
 *                   Undo last change
 *   a card with a   Open in browser, Save a copy
 *   file
 *   on the desktop  Show in folder
 *
 * A card that is still being built cannot be deleted (its worker may be
 * writing into that very folder): the item is there but disabled, with the
 * reason on hover.
 *
 * `useNodeCardActions` owns one menu and one open dialog for the whole
 * library; a card only reports where it was clicked.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Copy,
  Download,
  ExternalLink,
  Eye,
  FolderOpen,
  Loader2,
  MessageSquareText,
  PencilLine,
  Star,
  StarOff,
  Trash2,
  Undo2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  artifactDownloadUrl,
  artifactInlineUrl,
  artifactPageUrl,
  revealArtifact,
  revealOutput,
  useOutputsCapabilities,
} from "@/hooks/useOutputs";
import { useThemeValue } from "@/hooks/useTheme";
import { useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { askDodaiosToChange } from "./askDodaios";
import { isPendingCard } from "./libraryModel";
import { isTypedNode, type NodeCard } from "./nodeModel";
import { RenameNodeDialog } from "./RenameNodeDialog";
import { NodesApiError, isStillRunningError, useNodeActions } from "./useNodes";

/** The menu's width, so a caller can hang it under a button's right edge. */
export const NODE_MENU_WIDTH = 236;
const VIEWPORT_MARGIN = 8;

/** The card stands for a file the browser can open and the reader can save. */
export function cardHasFile(card: NodeCard): card is NodeCard & { path: string } {
  return card.path !== null && card.slug !== "";
}

/** Still being built: its run may be writing into the folder a delete would remove. */
export function cardIsWorking(card: NodeCard): boolean {
  return card.status === "building";
}

/** The app-relative URL "Open in browser" goes to, or null for a card without a file. */
export function cardBrowserUrl(card: NodeCard, theme: string): string | null {
  if (!cardHasFile(card)) return null;
  return card.visual_kind === "page"
    ? `${artifactPageUrl(card.slug, card.path)}?theme=${theme}`
    : artifactInlineUrl(card.slug, card.path);
}

export interface NodeMenuState {
  card: NodeCard;
  x: number;
  y: number;
  /** Where focus goes back to when the menu closes. */
  returnFocus: HTMLElement | null;
}

export interface NodeCardMenuProps {
  card: NodeCard;
  x: number;
  y: number;
  favorite: boolean;
  /** Desktop only: a headless host has no file manager to open. */
  canReveal: boolean;
  returnFocus?: HTMLElement | null;
  onDismiss: () => void;
  onOpen: () => void;
  onToggleFavorite: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onAsk: () => void;
  onRevert: () => void;
  onOpenExternal: () => void;
  onDownload: () => void;
  onReveal: () => void;
  onDelete: () => void;
}

export function NodeCardMenu({
  card,
  x,
  y,
  favorite,
  canReveal,
  returnFocus = null,
  onDismiss,
  onOpen,
  onToggleFavorite,
  onRename,
  onDuplicate,
  onAsk,
  onRevert,
  onOpenExternal,
  onDownload,
  onReveal,
  onDelete,
}: NodeCardMenuProps) {
  const t = useT();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const typed = isTypedNode(card);
  const hasFile = cardHasFile(card);
  const working = cardIsWorking(card);
  const revealable = canReveal && card.slug !== "" && card.origin !== "build";

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onDismiss();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) onDismiss();
    };
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("resize", onDismiss);
    window.addEventListener("blur", onDismiss);
    document.addEventListener("scroll", onDismiss, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("resize", onDismiss);
      window.removeEventListener("blur", onDismiss);
      document.removeEventListener("scroll", onDismiss, true);
    };
  }, [onDismiss]);

  // Focus goes back where it came from the moment the menu leaves, before a
  // dialog an item opened looks for the element to return to.
  const returnTo = useRef(returnFocus);
  returnTo.current = returnFocus;
  useLayoutEffect(
    () => () => {
      const target = returnTo.current;
      if (target && target.isConnected) target.focus({ preventScroll: true });
    },
    [],
  );

  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node) return;
    const { width, height } = node.getBoundingClientRect();
    const maxX = window.innerWidth - width - VIEWPORT_MARGIN;
    const maxY = window.innerHeight - height - VIEWPORT_MARGIN;
    node.style.left = `${Math.max(VIEWPORT_MARGIN, Math.min(x, maxX))}px`;
    node.style.top = `${Math.max(VIEWPORT_MARGIN, Math.min(y, maxY))}px`;
    node.style.visibility = "visible";
    node.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus({ preventScroll: true });
  }, [x, y]);

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") {
      // A menu is one stop: Tab leaves it for where the reader was.
      event.preventDefault();
      onDismiss();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? [],
    );
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

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={t("nodes.menu.aria")}
      data-testid="node-menu"
      onKeyDown={onMenuKeyDown}
      onContextMenu={(event) => event.preventDefault()}
      style={{ width: NODE_MENU_WIDTH, visibility: "hidden" }}
      className="fixed z-[100] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float"
    >
      <MenuItem icon={<Eye />} testId="node-menu-open" onClick={onOpen}>
        {t("nodes.menu.open")}
      </MenuItem>
      <MenuItem
        icon={favorite ? <StarOff /> : <Star />}
        testId="node-menu-favorite"
        onClick={onToggleFavorite}
      >
        {t(favorite ? "nodes.menu.favorite_remove" : "nodes.menu.favorite_add")}
      </MenuItem>
      {typed && (
        <>
          <MenuSeparator />
          <MenuItem icon={<PencilLine />} testId="node-menu-rename" onClick={onRename}>
            {t("nodes.menu.rename")}
          </MenuItem>
          <MenuItem icon={<Copy />} testId="node-menu-duplicate" onClick={onDuplicate}>
            {t("nodes.menu.duplicate")}
          </MenuItem>
          <MenuItem icon={<MessageSquareText />} testId="node-menu-ask" onClick={onAsk}>
            {t("nodes.menu.ask")}
          </MenuItem>
          <MenuItem icon={<Undo2 />} testId="node-menu-revert" onClick={onRevert}>
            {t("nodes.menu.revert")}
          </MenuItem>
        </>
      )}
      {(hasFile || revealable) && <MenuSeparator />}
      {hasFile && (
        <>
          <MenuItem icon={<ExternalLink />} testId="node-menu-open-external" onClick={onOpenExternal}>
            {t("nodes.menu.open_external")}
          </MenuItem>
          <MenuItem icon={<Download />} testId="node-menu-download" onClick={onDownload}>
            {t("nodes.menu.download")}
          </MenuItem>
        </>
      )}
      {revealable && (
        <MenuItem icon={<FolderOpen />} testId="node-menu-reveal" onClick={onReveal}>
          {t("nodes.menu.reveal")}
        </MenuItem>
      )}
      <MenuSeparator />
      <MenuItem
        icon={<Trash2 />}
        testId="node-menu-delete"
        onClick={onDelete}
        disabled={working}
        title={working ? t("nodes.delete.running") : undefined}
        destructive
      >
        {t("nodes.menu.delete")}
      </MenuItem>
    </div>,
    document.body,
  );
}

function MenuSeparator() {
  return <div role="separator" className="mx-1 my-1 h-px bg-border" />;
}

function MenuItem({
  icon,
  testId,
  onClick,
  disabled = false,
  title,
  destructive = false,
  children,
}: {
  icon: ReactNode;
  testId: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  destructive?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-base transition-colors duration-fast",
        "focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
        "[&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0",
        destructive
          ? "text-destructive hover:bg-destructive/10 focus-visible:bg-destructive/10"
          : "text-foreground hover:bg-secondary focus-visible:bg-secondary [&_svg]:text-muted-foreground",
      )}
    >
      <span aria-hidden className="contents">
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}

/* ------------------------------------------------------------------------- */

/** "Delete this?": the one step between a menu item and a gone folder. */
export function ConfirmDeleteNode({
  card,
  onCancel,
  onConfirm,
}: {
  /** The card to delete; null keeps the question closed. */
  card: NodeCard | null;
  onCancel: () => void;
  /** Rejects when the server refuses; the reason is then shown here. */
  onConfirm: (card: NodeCard) => Promise<void>;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keep = useRef<HTMLButtonElement>(null);

  const key = card?.key ?? null;
  useEffect(() => {
    setError(null);
    setBusy(false);
  }, [key]);

  const confirm = async () => {
    if (!card) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(card);
    } catch (failure) {
      setError(t(isStillRunningError(failure) ? "nodes.delete.running" : "nodes.delete.failed"));
    } finally {
      setBusy(false);
    }
  };

  const body = !card
    ? ""
    : isTypedNode(card)
      ? t("nodes.delete.body_node")
      : cardHasFile(card) && card.origin !== "run"
        ? t("nodes.delete.body_file")
        : t("nodes.delete.body_run");

  return (
    <Dialog.Root open={card !== null} onOpenChange={(open) => !open && !busy && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-testid="node-confirm-delete"
          onOpenAutoFocus={(event) => {
            // The safe answer has the focus: Enter keeps the node.
            event.preventDefault();
            keep.current?.focus();
          }}
          className="fixed left-1/2 top-[22%] z-[90] w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Dialog.Title className="text-lg font-semibold text-foreground-strong [overflow-wrap:anywhere]">
            {t("nodes.delete.title").replace("{0}", () => card?.title ?? "")}
          </Dialog.Title>
          <Dialog.Description className="mt-1.5 text-base text-muted-foreground">{body}</Dialog.Description>
          {error && (
            <p role="alert" className="mt-3 text-sm text-destructive" data-testid="node-delete-error">
              {error}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button ref={keep} type="button" variant="ghost" onClick={onCancel} disabled={busy}>
              {t("nodes.delete.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void confirm()}
              disabled={busy}
              data-testid="node-confirm-delete-confirm"
            >
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {t("nodes.delete.confirm")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* ------------------------------------------------------------------------- */

export interface NodeCardActionsOptions {
  favorites: ReadonlySet<string>;
  onToggleFavorite: (key: string) => void;
  onOpen: (card: NodeCard) => void;
}

export interface NodeCardActions {
  /** Open the menu for `card` at a viewport position. */
  openMenu: (card: NodeCard, x: number, y: number, returnFocus?: HTMLElement | null) => void;
  /** Ask before deleting `card` (the Delete key on a card). */
  askDelete: (card: NodeCard) => void;
  /** The key of the card whose menu is open, or null. */
  menuKey: string | null;
  /** The open menu and dialogs; render it once, anywhere. */
  layer: ReactNode;
}

/** One menu, one rename dialog and one delete question for the whole library. */
export function useNodeCardActions({
  favorites,
  onToggleFavorite,
  onOpen,
}: NodeCardActionsOptions): NodeCardActions {
  const t = useT();
  const theme = useThemeValue();
  const pushToast = useEventStore((s) => s.pushToast);
  const capabilities = useOutputsCapabilities();
  const actions = useNodeActions();
  const [menu, setMenu] = useState<NodeMenuState | null>(null);
  const [renaming, setRenaming] = useState<NodeCard | null>(null);
  const [deleting, setDeleting] = useState<NodeCard | null>(null);

  const openMenu = useCallback(
    (card: NodeCard, x: number, y: number, returnFocus: HTMLElement | null = null) => {
      // A placeholder is not a thing yet: there is nothing to act on.
      if (!isPendingCard(card)) setMenu({ card, x, y, returnFocus });
    },
    [],
  );
  const closeMenu = useCallback(() => setMenu(null), []);

  const askDelete = useCallback((card: NodeCard) => {
    if (!isPendingCard(card) && !cardIsWorking(card)) setDeleting(card);
  }, []);

  /** Close the menu, then act on the card it was opened for. */
  const run = (action: (card: NodeCard) => void) => () => {
    if (!menu) return;
    setMenu(null);
    action(menu.card);
  };

  const duplicate = (card: NodeCard) => {
    if (!isTypedNode(card)) return;
    actions.duplicateNode(card.id).then(
      () => pushToast("success", t("nodes.duplicate.done")),
      () => pushToast("error", t("nodes.duplicate.failed")),
    );
  };

  const revert = (card: NodeCard) => {
    if (!isTypedNode(card)) return;
    actions.revertNode(card.id).then(
      () => pushToast("success", t("nodes.revert.done")),
      (failure: unknown) => {
        const nothing = failure instanceof NodesApiError && failure.status === 400;
        pushToast(nothing ? "info" : "error", t(nothing ? "nodes.revert.nothing" : "nodes.revert.failed"));
      },
    );
  };

  const openExternal = (card: NodeCard) => {
    const url = cardBrowserUrl(card, theme);
    if (url) void openExternalUrl(`${window.location.origin}${url}`);
  };

  const download = (card: NodeCard) => {
    if (!cardHasFile(card)) return;
    const link = document.createElement("a");
    link.href = artifactDownloadUrl(card.slug, card.path);
    link.download = card.path.split("/").pop() ?? "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const reveal = (card: NodeCard) => {
    const request = cardHasFile(card) ? revealArtifact(card.slug, card.path) : revealOutput(card.slug);
    request.catch(() => pushToast("error", t("nodes.menu.reveal_failed")));
  };

  const layer = (
    <>
      {menu && (
        <NodeCardMenu
          card={menu.card}
          x={menu.x}
          y={menu.y}
          favorite={favorites.has(menu.card.key)}
          canReveal={capabilities.data?.native_file_actions === true}
          returnFocus={menu.returnFocus}
          onDismiss={closeMenu}
          onOpen={run(onOpen)}
          onToggleFavorite={run((card) => onToggleFavorite(card.key))}
          onRename={run(setRenaming)}
          onDuplicate={run(duplicate)}
          onAsk={run((card) => void askDodaiosToChange(card))}
          onRevert={run(revert)}
          onOpenExternal={run(openExternal)}
          onDownload={run(download)}
          onReveal={run(reveal)}
          onDelete={run(askDelete)}
        />
      )}
      <RenameNodeDialog
        card={renaming}
        onClose={() => setRenaming(null)}
        onRename={async (card, title) => {
          if (isTypedNode(card)) await actions.renameNode(card.id, title);
        }}
      />
      <ConfirmDeleteNode
        card={deleting}
        onCancel={() => setDeleting(null)}
        onConfirm={async (card) => {
          await actions.deleteNodeCard(card);
          setDeleting(null);
          pushToast("success", t("nodes.delete.done"));
        }}
      />
    </>
  );

  return { openMenu, askDelete, menuKey: menu?.card.key ?? null, layer };
}
