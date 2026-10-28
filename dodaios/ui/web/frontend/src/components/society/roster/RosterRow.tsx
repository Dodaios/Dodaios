/**
 * One roster row: a 40px face, the name, and one muted preview line. The face
 * carries a mark only when it says something (working, unread, waiting on
 * the person). The avatar opens the agent's profile, the rest of the row
 * opens its chat, and the whole row is the drag handle.
 */
import type {
  KeyboardEvent,
  MouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { MoreHorizontal } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { AgentSwatch } from "../AgentSwatch";
import { agentTint } from "../agentTint";
import type { SocietyAgent } from "../data";
import { readableWaiting, type RosterPreview, type RosterStatus } from "./rosterPreview";

export function StatusMark({ status, className }: { status: RosterStatus; className?: string }) {
  const t = useT();
  const label = statusLabel(status, t);
  return (
    <span
      role={status === "working" ? "status" : undefined}
      aria-label={label}
      title={label}
      data-status={status}
      data-testid="roster-status"
      className={cn("as-status", className)}
    />
  );
}

export function statusLabel(status: RosterStatus, t: (key: string) => string): string {
  switch (status) {
    case "needs-you":
      return t("society.shell.status_needs_you");
    case "working":
      return t("society.roster.thinking");
    case "unread":
      return t("society.roster.unread");
    case "paused":
      return t("society.state.paused");
    default:
      return t("society.state.idle");
  }
}

export function PreviewLine({ preview, className }: { preview: RosterPreview; className?: string }) {
  const t = useT();
  if (preview.kind === "waiting") {
    return (
      <span className={cn("as-row-preview", className)} data-kind="waiting" data-testid="roster-preview">
        <span className="as-preview-tag">{t("society.shell.preview_needs_you")}</span>
        {preview.text ? <> · {readableWaiting(preview.text, t)}</> : null}
      </span>
    );
  }
  if (preview.kind === "draft") {
    return (
      <span className={cn("as-row-preview", className)} data-kind="draft" data-testid="roster-preview">
        <span className="as-preview-tag">{t("society.shell.preview_draft")}</span> {preview.text}
      </span>
    );
  }
  return (
    <span className={cn("as-row-preview", className)} data-kind={preview.kind} data-testid="roster-preview">
      {preview.text}
    </span>
  );
}

export interface RosterRowProps {
  agent: SocietyAgent;
  displayName: string;
  status: RosterStatus;
  preview: RosterPreview;
  active: boolean;
  unread: boolean;
  hidden: boolean;
  reorderable: boolean;
  dragging: boolean;
  dropTarget: boolean;
  groupReady: boolean;
  menuOpen: boolean;
  /** 1–9 while the jump modifier is held; null otherwise. */
  shortcut: number | null;
  onPointerDown: (event: ReactPointerEvent) => void;
  onClickCapture: (event: MouseEvent) => void;
  onKeyDown: (event: KeyboardEvent) => void;
  onContextMenu: (event: MouseEvent) => void;
  onOpen: () => void;
  onOpenProfile: () => void;
  onHoverStart: (element: HTMLElement) => void;
  onHoverEnd: () => void;
}

export function RosterRow({
  agent,
  displayName,
  status,
  preview,
  active,
  unread,
  hidden,
  reorderable,
  dragging,
  dropTarget,
  groupReady,
  menuOpen,
  shortcut,
  onPointerDown,
  onClickCapture,
  onKeyDown,
  onContextMenu,
  onOpen,
  onOpenProfile,
  onHoverStart,
  onHoverEnd,
}: RosterRowProps) {
  const t = useT();
  return (
    <div
      data-agent-id={agent.agentId}
      data-active={active ? "true" : undefined}
      data-dragging={dragging ? "true" : undefined}
      data-drop={dropTarget ? "true" : undefined}
      data-group-ready={groupReady ? "true" : undefined}
      data-menu-open={menuOpen ? "true" : undefined}
      onPointerDown={onPointerDown}
      onClickCapture={onClickCapture}
      onKeyDown={onKeyDown}
      onContextMenu={onContextMenu}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse" || event.pointerType === undefined) onHoverStart(event.currentTarget);
      }}
      onPointerLeave={onHoverEnd}
      title={reorderable ? `${t("society.roster.reorder")} · ${t("society.shell.reorder_keys")}` : undefined}
      aria-keyshortcuts={reorderable ? "Alt+Shift+ArrowUp Alt+Shift+ArrowDown" : undefined}
      style={agentTint(agent)}
      className={cn(
        "as-row as-reveal-host select-none [&:has(>[data-row-main]:focus-visible)]:ring-2 [&:has(>[data-row-main]:focus-visible)]:ring-ring",
        reorderable ? "cursor-grab" : null,
        dragging ? "cursor-grabbing" : null,
        hidden && "opacity-60",
      )}
    >
      <button
        type="button"
        onClick={onOpenProfile}
        aria-label={t("society.profile_card.open").replace("{0}", displayName)}
        className="as-avatar rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <AgentSwatch agent={agent} size={40} />
        <StatusMark status={status} />
        {shortcut !== null ? <span className="as-shortcut-badge" aria-hidden>{shortcut}</span> : null}
      </button>
      <button
        type="button"
        onClick={onOpen}
        aria-current={active ? "true" : undefined}
        data-row-main
        className="flex min-w-0 flex-1 select-none flex-col justify-center gap-0.5 self-stretch text-left focus-visible:outline-none"
      >
        <span className={cn("as-row-name", unread && "font-semibold text-foreground-strong")}>{displayName}</span>
        {" "}
        <PreviewLine preview={preview} />
      </button>
      <button
        type="button"
        aria-label={t("society.roster.menu")}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onContextMenu(event);
        }}
        className="as-reveal as-round-button -mr-1 shrink-0" data-size="sm"
        data-testid="roster-row-more"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
