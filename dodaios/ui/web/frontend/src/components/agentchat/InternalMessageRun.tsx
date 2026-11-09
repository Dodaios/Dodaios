import { Fragment, useState } from "react";

import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useT } from "@/i18n";

import { InternalMessageBubble, type InternalParticipant } from "./InternalMessageBubble";
import { useOpenPairConversation } from "./PairConversation";
import type { InternalMessageItem, TimelineItem } from "./reduce";

/** Consecutive agent-to-agent messages, drawn as one centred line. */
export interface InternalRunItem {
  type: "internal_run";
  id: string;
  items: InternalMessageItem[];
}

/** A pause this long between two agent messages starts a new line. */
const RUN_GAP_MS = 20 * 60 * 1000;

/**
 * Folds every stretch of back-to-back agent messages into one run, so the
 * chat reads "5 messages with Scout" instead of five cards. A pause of
 * {@link RUN_GAP_MS} (the same gap that earns a time stamp) or any other
 * item in between starts a new run. `keep` says which internal items may
 * join a run at all (coding-thread activity keeps its own row).
 */
export function groupInternalRuns(
  items: TimelineItem[],
  keep: (item: InternalMessageItem) => boolean = () => true,
): (TimelineItem | InternalRunItem)[] {
  const out: (TimelineItem | InternalRunItem)[] = [];
  let run: InternalRunItem | null = null;
  for (const item of items) {
    if (item.type === "internal" && keep(item)) {
      const last = run?.items.at(-1);
      if (run && last && item.tsMs - last.tsMs < RUN_GAP_MS) {
        run.items.push(item);
        continue;
      }
      run = { type: "internal_run", id: item.id, items: [item] };
      out.push(run);
      continue;
    }
    run = null;
    out.push(item);
  }
  return out;
}

interface Counterpart {
  id: string;
  name: string;
}

/** Who the chat owner talked to in this run, each once, in order of appearance. */
export function runCounterparts(items: InternalMessageItem[], recipientName = ""): Counterpart[] {
  const seen = new Map<string, Counterpart>();
  for (const item of items) {
    const who = item.outgoing
      ? { id: item.outgoing.recipientId, name: item.outgoing.recipientName || recipientName }
      : { id: item.message.sender_id, name: item.message.sender_name };
    const key = who.id || who.name;
    if (key && !seen.has(key)) seen.set(key, who);
  }
  return [...seen.values()];
}

const NEUTRAL = { primary: "#888", secondary: "#555", accent: "#aaa" };

/**
 * One quiet, centred line for a run of agent-to-agent messages:
 * "Message sent · Grok Bot", "Message from Scout", or
 * "5 messages with Grok Bot and Marketing Lead". Each name opens the
 * read-only conversation between the two agents where the chat offers one;
 * the line itself unfolds the messages in place.
 */
export function InternalMessageRun({
  run,
  agentsById,
  recipientName,
}: {
  run: InternalRunItem;
  agentsById?: Record<string, InternalParticipant>;
  recipientName?: string;
}) {
  const t = useT();
  const openPair = useOpenPairConversation();
  const [open, setOpen] = useState(false);
  const { items } = run;
  const people = runCounterparts(items, recipientName);
  const failed = items.filter((item) => item.message.status === "failed").length;
  const only = items.length === 1 ? items[0] : null;
  const lead = only
    ? only.outgoing
      ? t("agent_chat.run_sent")
      : t("agent_chat.run_from")
    : t("agent_chat.run_count").replace("{0}", String(items.length));
  const toggle = () => setOpen((value) => !value);

  return (
    <div data-testid="agent-message-run" data-message-id={run.id} data-count={items.length} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1 py-1 text-center text-xs text-muted-foreground">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-label={open ? t("agent_chat.internal_collapse") : t("agent_chat.internal_expand")}
          data-testid="agent-message-run-toggle"
          className="rounded px-0.5 hover:text-foreground"
        >
          {lead}
        </button>
        {people.map((who, index) => {
          const face = agentsById?.[who.id] ?? { name: who.name, figure: null, palette: NEUTRAL };
          const canPair = Boolean(openPair && who.id && who.id !== "user");
          return (
            <Fragment key={who.id || who.name}>
              {index > 0 ? <span>{index === people.length - 1 ? t("agent_chat.run_and") : ","}</span> : null}
              <button
                type="button"
                onClick={() => (canPair ? openPair?.(who) : toggle())}
                title={canPair ? t("agent_chat.pair_open") : undefined}
                data-testid="agent-message-run-person"
                className="inline-flex items-center gap-1 rounded px-0.5 text-foreground-secondary hover:text-foreground"
              >
                <AgentSwatch agent={face} size={16} />
                <span className="max-w-[12rem] truncate">{who.name}</span>
              </button>
            </Fragment>
          );
        })}
        {failed > 0 ? (
          <span className="text-destructive">· {t("agent_chat.run_failed").replace("{0}", String(failed))}</span>
        ) : null}
      </div>
      {open ? (
        <div className="flex flex-col gap-2" data-testid="agent-message-run-messages">
          {items.map((item) => (
            <InternalMessageBubble
              key={item.id}
              item={item}
              sender={agentsById?.[item.message.sender_id] ?? null}
              recipientName={recipientName}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
