/**
 * The larger identity a row shows after the pointer rests on it: face, name,
 * role, what the agent is doing, and the latest words in its chat. Read-only
 * and pointer-transparent, so it never steals a click or a drag.
 */
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useT } from "@/i18n";

import { AgentSwatch } from "../AgentSwatch";
import { agentTint } from "../agentTint";
import type { SocietyAgent } from "../data";
import { previewText, type RosterStatus, type WaitingReason } from "./rosterPreview";
import { StatusMark, statusLabel } from "./RosterRow";

export interface HoverCardData {
  agent: SocietyAgent;
  displayName: string;
  status: RosterStatus;
  reason: WaitingReason | null;
  lastMessage?: string;
  draft?: string;
  timeLabel?: string;
  anchor: DOMRect;
}

const GAP = 10;

export function RosterHoverCard({ data }: { data: HoverCardData }) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const { width, height } = element.getBoundingClientRect();
    const fitsRight = data.anchor.right + GAP + width <= window.innerWidth - 8;
    const left = fitsRight ? data.anchor.right + GAP : Math.max(8, data.anchor.left - GAP - width);
    const top = Math.max(8, Math.min(data.anchor.top - 6, window.innerHeight - height - 8));
    setPosition({ left, top });
  }, [data.anchor]);

  const last = previewText(data.lastMessage);
  const draft = previewText(data.draft);
  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      data-testid="roster-hover-card"
      className="agent-section as-hovercard"
      style={{ ...agentTint(data.agent), left: position?.left ?? -9999, top: position?.top ?? -9999 }}
    >
      <div className="flex items-center gap-3">
        <span className="as-avatar">
          <AgentSwatch agent={data.agent} size={44} />
          <StatusMark status={data.status} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground-strong">{data.displayName}</p>
          {data.agent.title ? <p className="truncate text-xs text-muted-foreground">{data.agent.title}</p> : null}
        </div>
      </div>
      <p className={data.status === "needs-you" ? "mt-3 text-xs font-medium text-warning" : "mt-3 text-xs text-muted-foreground"}>
        {data.status === "needs-you" && data.reason?.summary
          ? `${t("society.shell.preview_needs_you")} · ${previewText(data.reason.summary)}`
          : statusLabel(data.status, t)}
        {data.timeLabel ? <span className="text-muted-foreground"> · {data.timeLabel}</span> : null}
      </p>
      {last ? <p className="mt-2 line-clamp-3 text-[13px] leading-[19px] text-foreground">{last}</p> : null}
      {draft ? (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          <span className="as-preview-tag">{t("society.shell.preview_draft")}</span> {draft}
        </p>
      ) : null}
    </div>,
    document.body,
  );
}
