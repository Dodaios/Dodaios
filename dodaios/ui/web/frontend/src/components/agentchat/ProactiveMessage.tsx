import { fill, useT } from "@/i18n";
import { useEventStore } from "@/store/events";

import { LeadReply } from "./LeadReply";
import type { NoticeItem } from "./reduce";

/**
 * Something the assistant says in its chat on its own, as a message of its
 * own: the memory tidy-up ("I tidied up my memory of you …"),
 * an event that matched a standing rule. The words come with the notice
 * (`voice`, written by `dodaios/agent_chat/proactive_voice.py` in the person's
 * language). Until 2026-11-18 these were a grey centred line ("Update from
 * Dodaios · Tidied the memory: merged 2 - review it in Mem…"), which read as a
 * log entry, in English, cut short.
 *
 * Reminders and calendar appointments have their own message
 * (`reminders/ReminderDueMessage`), because they carry actions.
 */

/** Notice kinds drawn here. */
export const PROACTIVE_KINDS: ReadonlySet<string> = new Set(["memory_tidy", "event_trigger"]);

const TIDY_PARTS = ["merged", "resolved", "retired", "reworded"] as const;

const str = (value: unknown): string => (typeof value === "string" ? value : "");

/** The changes of a tidy-up, from its fields or, on an older notice, its English sentence. */
function tidyCounts(item: NoticeItem): Record<(typeof TIDY_PARTS)[number], number> {
  const out = { merged: 0, resolved: 0, retired: 0, reworded: 0 };
  for (const part of TIDY_PARTS) {
    const value = item.data[part];
    if (typeof value === "number") out[part] = value;
    else {
      const match = new RegExp(`\\b${part} (\\d+)`).exec(item.text);
      if (match) out[part] = Number(match[1]);
    }
  }
  return out;
}

/** What a notice from before the assistant wrote its own words says. */
export function plainProactiveWords(item: NoticeItem, t: (key: string) => string): string {
  if (item.kind !== "memory_tidy") return item.text.trim();
  const counts = tidyCounts(item);
  const parts = TIDY_PARTS.filter((part) => counts[part] > 0).map((part) => (
    counts[part] === 1 ? t(`agent_chat.proactive_tidy_${part}_one`)
      : fill(t(`agent_chat.proactive_tidy_${part}`), { n: String(counts[part]) })
  ));
  if (!parts.length) return t("agent_chat.proactive_tidy_plain");
  const changes = parts.length === 1 ? parts[0]
    : `${parts.slice(0, -1).join(", ")}${t("agent_chat.proactive_and")}${parts[parts.length - 1]}`;
  return fill(t("agent_chat.proactive_tidy"), { changes });
}

export function ProactiveMessage({ item }: { item: NoticeItem }) {
  const t = useT();
  const words = str(item.data.voice).trim() || plainProactiveWords(item, t);
  if (!words) return null;
  return (
    <div className="lead-turn" data-testid="proactive-message" data-kind={item.kind} data-message-id={item.id}>
      <div className="lead-face-lane" aria-hidden />
      <div className="lead-turn-body">
        <LeadReply text={words} live={false} />
        {item.kind === "memory_tidy" ? (
          <button type="button" data-testid="proactive-open-memory"
            onClick={() => useEventStore.getState().setActiveSection("memory")}
            className="ml-3 mt-1 self-start rounded px-1 py-0.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {t("agent_chat.proactive_open_memory")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
