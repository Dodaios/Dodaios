import { useEffect, useState } from "react";
import { Globe, Lock, ShieldAlert } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { openAgent } from "@/views/society/agentNavigation";
import { requestAgentBrowserStage } from "@/components/home/chatBrowser/openEvent";
import { useLatestBrowserFrame } from "@/components/society/card/liveFrames";
import type { NoticeItem } from "./reduce";

/** The note a "Take over" answer carries (``bridge.TAKEN_OVER_NOTE``). */
export const TAKEN_OVER_NOTE = "taken_over";
/**
 * The buttons wait this long after the card appears, so a click or an Enter
 * meant for something else never answers it.
 */
export const ARM_DELAY_MS = 500;

/** Kinds of step that have their own words on the card (``commit_gate._KINDS``). */
const KINDS = new Set([
  "buy", "transfer", "payment_details", "close_account", "authorize",
  "cancel", "book", "send", "publish", "delete", "accept", "confirm",
]);

/**
 * Answer one row of the approvals table; every surface answers the same row.
 * Returns how the row stands afterwards ("approved" | "declined"), or "" when
 * the answer did not arrive. A row that was already answered elsewhere keeps
 * that answer, and the card shows it.
 */
async function answer(approvalId: string, approve: boolean, note = ""): Promise<string> {
  const response = await fetch(`/api/society/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(note ? { approve, note } : { approve }),
  });
  if (!response.ok) return "";
  let state = "";
  try {
    const body = (await response.json()) as { approval?: { state?: string } };
    state = String(body?.approval?.state ?? "");
  } catch {
    state = "";
  }
  if (state === "approved") return "approved";
  if (state === "denied" || state === "blocked") return note === TAKEN_OVER_NOTE ? TAKEN_OVER_NOTE : "declined";
  return approve ? "approved" : "declined";
}

function openBrowser(agentId: string, takeover: boolean) {
  if (!requestAgentBrowserStage(agentId, { takeover })) openAgent(agentId);
}

/**
 * The card for work that waits in place for a yes: a browser run paused at the
 * step that commits something (buy, pay, send, delete), or a tool whose rules
 * want the person.
 *
 * It names the step, the site and what the page says about it. A browser step
 * shows the page itself, live and small, so the person sees what is about to
 * be clicked; a click on the picture opens the browser large. Allow runs
 * exactly that step, Deny ends the work, Take over hands the page to the
 * person, who does the step themselves. Money and the person's account ask in
 * every permission mode, Bypass too; the card says so. Once answered it is one
 * line that says how.
 */
export function ApprovalRequestCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [armed, setArmed] = useState(false);
  const approvalId = String(item.data.approval_id ?? "");
  const agentId = String(item.data.agent_id ?? "");
  const label = String(item.data.label ?? "");
  const where = String(item.data.where ?? "");
  const detail = String(item.data.detail ?? "");
  const browser = item.data.browser === true && agentId !== "";
  const always = String(item.data.severity ?? "") === "confirm";
  const kind = String(item.data.step_kind ?? "");
  // The timeline closes the card when the work reports how it ended. The
  // person's own click closes it at once, so it never keeps live buttons when
  // that report does not come (the app restarted while the work waited).
  const [answered, setAnswered] = useState("");
  const resolved = item.resolved || answered;
  const closed = resolved !== "";
  const frame = useLatestBrowserFrame(agentId, browser && !closed);
  useEffect(() => {
    if (closed) return undefined;
    const timer = window.setTimeout(() => setArmed(true), ARM_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [closed]);
  const title = kind === "payment_details"
    ? t(where ? "society.chat.approval_request_payment_on" : "society.chat.approval_request_payment").replace("{where}", where)
    : label
    ? t(where ? "society.chat.approval_request_click_on" : "society.chat.approval_request_click")
        .replace("{label}", label)
        .replace("{where}", where)
    : t("society.chat.approval_request_title");
  const closedKey =
    resolved === "approved" ? "society.chat.approval_request_approved"
    : resolved === "declined" ? "society.chat.approval_request_declined"
    : resolved === TAKEN_OVER_NOTE ? "society.chat.approval_request_taken_over"
    : "society.chat.approval_request_expired";
  const decide = async (approve: boolean, note = "") => {
    if (busy || !armed || !approvalId) return;
    setBusy(true);
    setFailed(false);
    try {
      const state = await answer(approvalId, approve, note);
      if (state) setAnswered(state);
      else setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  const takeOver = async () => {
    if (!browser) return;
    await decide(false, TAKEN_OVER_NOTE);
    openBrowser(agentId, true);
  };
  if (closed) {
    // One line in the conversation: what was asked and how it ended.
    return (
      <div data-message-id={item.id} data-testid="approval-request-card" data-state="closed"
        className="mx-auto flex max-w-[85%] items-center gap-2 px-1 py-1 text-xs text-muted-foreground">
        <Lock aria-hidden size={12} className="shrink-0" />
        <span className="min-w-0 truncate" data-testid="approval-request-closed">
          {t(closedKey)} · {item.text || title}
        </span>
      </div>
    );
  }
  const button = "inline-flex h-8 items-center rounded-md px-3 text-[13px] font-medium transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
  return (
    <div data-message-id={item.id} data-testid="approval-request-card" data-state="open"
      data-severity={always ? "confirm" : "ask"} role="group" aria-label={title}
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); void decide(false); }
      }}
      className={cn(
        "mx-auto flex w-full max-w-[min(85%,520px)] flex-col gap-3 rounded-lg border bg-card px-4 py-3 text-body shadow-sm",
        always ? "border-amber-500/60" : "border-border",
      )}>
      <div className="flex items-center gap-2 text-xs">
        <span data-testid="approval-request-chip"
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium",
            always ? "bg-amber-500/15 text-amber-700 dark:text-amber-300" : "bg-secondary text-foreground",
          )}>
          <ShieldAlert aria-hidden size={12} />
          {t(always ? "society.chat.approval_request_always" : "society.chat.approval_request_needs_ok")}
        </span>
        {KINDS.has(kind) ? (
          <span className="text-muted-foreground" data-testid="approval-request-kind">
            {t(`society.chat.approval_request_kind_${kind}`)}
          </span>
        ) : null}
        {where ? (
          <span className="ml-auto inline-flex min-w-0 items-center gap-1 text-muted-foreground">
            <Globe aria-hidden size={12} className="shrink-0" />
            <span className="truncate font-medium text-foreground" data-testid="approval-request-where">{where}</span>
          </span>
        ) : null}
      </div>
      <span className="font-medium text-foreground" data-testid="approval-request-title">{title}</span>
      {browser ? (
        <button type="button" data-testid="approval-request-live" onClick={() => openBrowser(agentId, false)}
          aria-label={t("society.chat.approval_request_live")}
          className="relative block aspect-[16/10] w-full max-w-[360px] cursor-zoom-in overflow-hidden rounded-md border border-border bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {frame ? (
            <img src={frame} alt="" className="h-full w-full object-cover object-top" draggable={false} />
          ) : (
            <span className="absolute inset-0 grid place-items-center text-xs text-muted-foreground">
              {t("society.chat.approval_request_live_open")}
            </span>
          )}
          <span className="absolute bottom-2 left-2 inline-flex items-center gap-1.5 rounded-full bg-background/90 px-2 py-0.5 text-[11px] text-foreground shadow-sm">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" aria-hidden />
            {t("society.chat.approval_request_paused")}
          </span>
        </button>
      ) : null}
      {label ? null : <span className="text-muted-foreground">{item.text}</span>}
      {detail ? <span className="text-muted-foreground" data-testid="approval-request-detail">{detail}</span> : null}
      {always ? (
        <span className="text-xs text-muted-foreground" data-testid="approval-request-always-note">
          {t("society.chat.approval_request_always_note")}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid="approval-request-yes" disabled={busy || !armed} onClick={() => void decide(true)}
          className={cn(button, "bg-primary text-primary-foreground hover:opacity-90")}>
          {t("society.chat.approval_request_allow")}
        </button>
        <button type="button" data-testid="approval-request-no" disabled={busy || !armed} onClick={() => void decide(false)}
          className={cn(button, "border border-border hover:bg-accent")}>
          {t("society.chat.approval_request_deny")}
        </button>
        {browser ? (
          <button type="button" data-testid="approval-request-take-over" disabled={busy || !armed}
            onClick={() => void takeOver()}
            className={cn(button, "ml-auto text-foreground hover:bg-accent")}>
            {t("society.chat.approval_request_take_over")}
          </button>
        ) : null}
      </div>
      {failed ? (
        <span className="text-xs text-destructive" data-testid="approval-request-failed">
          {t("society.chat.approval_request_failed")}
        </span>
      ) : null}
    </div>
  );
}

/**
 * An action Dodaios refused for good (``action_policy`` block: the dark web).
 * No buttons: nothing the person clicks makes it run. It says what and why.
 */
export function ActionBlockedCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const where = String(item.data.where ?? "");
  const category = String(item.data.category ?? "");
  const reason = category === "dark_web" ? t("society.chat.action_blocked_dark_web") : item.text;
  return (
    <div data-message-id={item.id} data-testid="action-blocked-card" data-category={category}
      className="mx-auto flex w-full max-w-[min(85%,520px)] flex-col gap-1 rounded-md border border-l-4 border-border border-l-destructive bg-card px-4 py-2.5 text-body">
      <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <ShieldAlert aria-hidden size={14} className="text-destructive" />
        {t("society.chat.action_blocked_title")}
        {where ? <span className="font-normal text-muted-foreground">· {where}</span> : null}
      </span>
      <span className="text-muted-foreground" data-testid="action-blocked-reason">{reason}</span>
      <span className="text-xs text-muted-foreground">{t("society.chat.action_blocked_note")}</span>
    </div>
  );
}
