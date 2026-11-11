import { useT } from "@/i18n";
import { openAgent } from "@/views/society/agentNavigation";
import type { NoticeItem } from "./reduce";

/**
 * One written card when the agent asks the person to act in its browser
 * (CAPTCHA, sign-in, a second factor): the reason, and a button that opens the
 * live browser view where the person takes over and hands back. It never
 * speaks, and once handed back it only says so.
 */
export function BrowserTakeoverNotice({ item }: { item: NoticeItem }) {
  const t = useT();
  const agentId = String(item.data.agent_id ?? "");
  const closed = item.resolved !== "";
  return (
    <div data-message-id={item.id} data-testid="browser-takeover-card" data-state={closed ? "closed" : "open"}
      className="mx-auto flex max-w-[85%] flex-col gap-2 rounded-lg bg-card px-4 py-3 text-body">
      <span className="font-medium text-foreground">{t("society.chat.browser_takeover_title")}</span>
      <span className="text-muted-foreground">{item.text}</span>
      {closed ? (
        <span className="text-xs text-muted-foreground" data-testid="browser-takeover-closed">
          {t(item.resolved === "handed_back" ? "society.chat.browser_takeover_done" : "society.chat.browser_takeover_expired")}
        </span>
      ) : agentId ? (
        <div className="flex flex-wrap gap-2">
          <button type="button" data-testid="browser-takeover-open" onClick={() => openAgent(agentId)}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("society.chat.browser_takeover_open")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
