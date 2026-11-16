import { useState } from "react";
import { useT } from "@/i18n";
import { openAgent } from "@/views/society/agentNavigation";
import { requestAgentBrowserStage } from "@/components/home/chatBrowser/openEvent";
import type { NoticeItem } from "./reduce";

/**
 * Answer one row of the approvals table; every surface answers the same row.
 * Returns how the row stands afterwards ("approved" | "declined"), or "" when
 * the answer did not arrive. A row that was already answered elsewhere keeps
 * that answer, and the card shows it.
 */
async function answer(approvalId: string, approve: boolean): Promise<string> {
  const response = await fetch(`/api/society/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approve }),
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
  if (state === "denied" || state === "blocked") return "declined";
  return approve ? "approved" : "declined";
}

/**
 * The card for work that waits in place for a yes: a browser run paused at the
 * click that commits something (cancel, buy, send, delete), or a tool whose
 * rules want the person. It says what exactly is about to happen and where,
 * with Yes and No; the work goes on when the person answers. Once answered it
 * only says how.
 */
export function ApprovalRequestCard({ item }: { item: NoticeItem }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const approvalId = String(item.data.approval_id ?? "");
  const agentId = String(item.data.agent_id ?? "");
  const label = String(item.data.label ?? "");
  const where = String(item.data.where ?? "");
  const detail = String(item.data.detail ?? "");
  // The timeline closes the card when the work reports how it ended. The
  // person's own click closes it at once, so it never keeps live buttons when
  // that report does not come (the app restarted while the work waited).
  const [answered, setAnswered] = useState("");
  const resolved = item.resolved || answered;
  const closed = resolved !== "";
  const title = label
    ? t(where ? "society.chat.approval_request_click_on" : "society.chat.approval_request_click")
        .replace("{label}", label)
        .replace("{where}", where)
    : t("society.chat.approval_request_title");
  const closedKey =
    resolved === "approved" ? "society.chat.approval_request_approved"
    : resolved === "declined" ? "society.chat.approval_request_declined"
    : "society.chat.approval_request_expired";
  const decide = async (approve: boolean) => {
    if (busy || !approvalId) return;
    setBusy(true);
    setFailed(false);
    try {
      const state = await answer(approvalId, approve);
      if (state) setAnswered(state);
      else setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-message-id={item.id} data-testid="approval-request-card" data-state={closed ? "closed" : "open"}
      className="mx-auto flex max-w-[85%] flex-col gap-2 rounded-lg bg-card px-4 py-3 text-body">
      <span className="font-medium text-foreground" data-testid="approval-request-title">{title}</span>
      {label ? null : <span className="text-muted-foreground">{item.text}</span>}
      {detail ? <span className="text-muted-foreground" data-testid="approval-request-detail">{detail}</span> : null}
      {closed ? (
        <span className="text-xs text-muted-foreground" data-testid="approval-request-closed">{t(closedKey)}</span>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" data-testid="approval-request-yes" disabled={busy} onClick={() => void decide(true)}
            className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
            {t("society.chat.approval_request_yes")}
          </button>
          <button type="button" data-testid="approval-request-no" disabled={busy} onClick={() => void decide(false)}
            className="rounded-md border border-border px-3 py-1 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
            {t("society.chat.approval_request_no")}
          </button>
          {item.data.browser && agentId ? (
            <button type="button" data-testid="approval-request-open"
              onClick={() => { if (!requestAgentBrowserStage(agentId)) openAgent(agentId); }}
              className="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t("society.chat.browser_takeover_open")}
            </button>
          ) : null}
        </div>
      )}
      {failed ? (
        <span className="text-xs text-destructive" data-testid="approval-request-failed">
          {t("society.chat.approval_request_failed")}
        </span>
      ) : null}
    </div>
  );
}
