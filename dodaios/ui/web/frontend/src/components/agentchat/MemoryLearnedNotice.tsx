import { useState } from "react";
import { Brain } from "lucide-react";

import { useT } from "@/i18n";
import { forgetMemory } from "@/lib/personalMemoryApi";
import { anchorOf, jumpToMessage, type MessageAnchor } from "@/lib/memorySource";
import type { NoticeItem } from "./reduce";

type Learned = { op: string; id: string; text: string; anchor: MessageAnchor | null };

const LABEL: Record<string, string> = {
  added: "society.chat.memory_learned_added",
  updated: "society.chat.memory_learned_updated",
  ended: "society.chat.memory_learned_ended",
};

function rowsOf(item: NoticeItem): Learned[] {
  const raw = Array.isArray(item.data.items) ? item.data.items : [];
  return raw
    .map((row) => row as Record<string, unknown>)
    .filter((row) => typeof row.text === "string" && row.text)
    .map((row) => ({
      op: String(row.op ?? "added"),
      id: String(row.id ?? ""),
      text: String(row.text),
      // Every row here was learned in this conversation (the background review).
      anchor: anchorOf({ ...row, via: "review" }),
    }));
}

const LINK =
  "shrink-0 rounded px-1 underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * What the assistant just learned about the person, as quiet lines in the
 * conversation: "Remembered: ..." with an undo that forgets it again
 * (agent_chat/lead.py `post_learned`), and a link back to the message it was
 * learned from. Written only, never spoken.
 */
export function MemoryLearnedNotice({ item }: { item: NoticeItem }) {
  const t = useT();
  const [undone, setUndone] = useState<Record<string, boolean>>({});
  const [missing, setMissing] = useState<Record<string, boolean>>({});
  const rows = rowsOf(item);
  if (rows.length === 0) return null;
  const undo = (id: string) => {
    void forgetMemory(id).then(
      () => setUndone((s) => ({ ...s, [id]: true })),
      () => undefined,
    );
  };
  const show = (row: Learned) => {
    if (!row.anchor) return;
    void jumpToMessage(row.anchor, { timeoutMs: 0 }).then((found) => {
      if (!found) setMissing((s) => ({ ...s, [row.id || row.text]: true }));
    });
  };
  return (
    <div data-message-id={item.id} data-testid="memory-learned" className="mx-auto flex max-w-[85%] flex-col gap-1 py-1">
      {rows.map((row) => (
        <p key={row.id || row.text} className="flex items-baseline gap-2 text-xs text-muted-foreground">
          <Brain aria-hidden className="h-3.5 w-3.5 shrink-0 self-center" />
          <span className={undone[row.id] ? "line-through" : undefined}>
            <span className="font-medium text-foreground">{t(LABEL[row.op] ?? LABEL.added)}:</span> {row.text}
          </span>
          {row.anchor && !undone[row.id] ? (
            missing[row.id || row.text] ? (
              <span className="shrink-0" data-testid="memory-learned-source-missing">{t("memory_trust.source_not_loaded")}</span>
            ) : (
              <button type="button" onClick={() => show(row)} data-testid="memory-learned-source"
                title={t("memory_trust.source_title")} className={LINK}>
                {t("memory_trust.source_link")}
              </button>
            )
          ) : null}
          {row.op === "added" && row.id ? (
            undone[row.id] ? (
              <span className="shrink-0">{t("society.chat.memory_learned_undone")}</span>
            ) : (
              <button type="button" onClick={() => undo(row.id)} data-testid="memory-learned-undo" className={LINK}>
                {t("society.chat.memory_learned_undo")}
              </button>
            )
          ) : null}
        </p>
      ))}
    </div>
  );
}
