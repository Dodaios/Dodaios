import { useI18nStore, useT } from "@/i18n";
import { localeForUiLanguage } from "@/components/runs/format";
import type { TimelineItem, UserItem } from "./reduce";

/**
 * The line under the person's own message in the conversation look, the way
 * a messenger shows it: "Sent 21:56" once the message is in, "Read 21:56"
 * from the moment the assistant took it up (the person's request, 2026-11-12).
 */
export interface Receipt {
  /** The assistant took the message up: its answering turn started. */
  read: boolean;
  /** When it was read; when it was sent while it still waits. */
  atMs: number;
}

/**
 * The receipt of every message the person wrote, by item id. A message is
 * read when the turn that answers it starts: the next turn after it, with no
 * other message of theirs in between.
 */
export function messageReceipts(items: readonly TimelineItem[]): Map<string, Receipt> {
  const out = new Map<string, Receipt>();
  let waiting: UserItem | null = null;
  for (const item of items) {
    if (item.type === "user") {
      // A command's turn or an earlier request's result: the turn after it is not an answer to the person.
      waiting = item.origin ? null : item;
      if (waiting) out.set(item.id, { read: false, atMs: item.tsMs });
    } else if (item.type === "turn" && waiting) {
      // A turn whose start was never recorded is stamped with the message's own time.
      out.set(waiting.id, { read: true, atMs: item.startedMs || waiting.tsMs });
      waiting = null;
    }
  }
  return out;
}

/** Today shows the clock only; any other day leads with the date, the way a messenger does. */
export function stampLabel(at: Date, now: Date = new Date()): string {
  const locale = localeForUiLanguage(useI18nStore.getState().ui);
  const time = at.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  if (at.toDateString() === now.toDateString()) return time;
  const date = at.toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${date}, ${time}`;
}

/** "Read 21:56" under the person's bubble; nothing for a message without a usable time. */
export function MessageReceipt({ receipt }: { receipt: Receipt | undefined }) {
  const t = useT();
  if (!receipt || !receipt.atMs || !Number.isFinite(receipt.atMs)) return null;
  const key = receipt.read ? "society.chat.message_read" : "society.chat.message_sent";
  return (
    <span
      data-testid="agent-message-receipt"
      data-read={receipt.read ? "true" : "false"}
      className="self-end pr-1 text-xs tabular-nums text-muted-foreground"
    >
      {t(key).replace("{0}", stampLabel(new Date(receipt.atMs)))}
    </span>
  );
}
