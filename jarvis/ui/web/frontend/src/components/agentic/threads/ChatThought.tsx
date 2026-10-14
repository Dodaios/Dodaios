import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import type { ReasoningBlock, TurnItem } from "@/components/agentchat/reduce";
import { traceDuration } from "@/components/agentchat/traceEntries";

/** The thinking as it reads: a quiet column under a hairline, a step below the answer. */
const BODY = cn(
  "prose prose-sm max-w-none border-l-2 border-border pl-3 text-sm leading-6 text-muted-foreground dark:prose-invert [overflow-wrap:anywhere]",
  "prose-p:my-1.5 prose-p:text-muted-foreground prose-li:text-muted-foreground prose-strong:text-foreground-secondary",
  "prose-headings:my-1.5 prose-headings:text-sm prose-headings:font-medium prose-headings:text-foreground-secondary prose-pre:text-xs",
);

/** Time since `since`, counted in place: the turn never re-renders to tick. */
function Ticker({ since }: { since: number }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const tick = () => {
      if (ref.current) ref.current.textContent = traceDuration(Math.max(0, Date.now() - since));
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  return <span ref={ref} className="text-xs tabular-nums text-faint-foreground" />;
}

/**
 * A chat answer's thinking, as one piece.
 *
 * While the model thinks, a shimmering "Thinking" with its clock, and under
 * it the thought itself as it streams: the newest lines in view, the older
 * ones fading out at the top. Once the answer starts, all of it folds into
 * one line, "Thought for 4s", that opens the whole text on a click. Several
 * reasoning blocks of one turn read as a single thought, never as a stack of
 * "Thinking" lines.
 */
export function ChatThought({ turn, answering }: { turn: TurnItem; answering: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  const stream = useRef<HTMLDivElement | null>(null);
  const blocks = useMemo(
    () => turn.blocks.filter((block): block is ReasoningBlock => block.kind === "reasoning"),
    [turn.blocks],
  );
  const text = useMemo(() => blocks.map((block) => block.text.trim()).filter(Boolean).join("\n\n"), [blocks]);
  // Thinking lasts until the answer begins; a model that never says what it
  // thinks still shows that it is at work.
  const live = turn.status === "running" && (!answering || blocks.some((block) => block.live));
  const thoughtMs = blocks.reduce((sum, block) => sum + (block.durationMs ?? 0), 0);

  // The newest words stay in view while they arrive.
  useLayoutEffect(() => {
    const box = stream.current;
    if (!box || !live) return;
    box.scrollTop = box.scrollHeight;
    setClipped(box.scrollHeight > box.clientHeight + 1);
  }, [text, live]);

  if (!live && blocks.length === 0) return null;

  if (live) {
    return <div data-testid="chat-thought" data-live="true" className="min-w-0 space-y-1.5">
      <div role="status" className="flex h-7 items-center gap-2 text-sm">
        <span className="thinking-shimmer font-medium">{t("thread_turn.thinking")}</span>
        <Ticker since={blocks[0]?.startedMs ?? turn.startedMs} />
      </div>
      {text && <div ref={stream} data-testid="chat-thought-stream"
        className={cn("max-h-32 overflow-hidden", clipped && "[mask-image:linear-gradient(to_bottom,transparent,black_3rem)]")}>
        <div className={BODY}><ChatMarkdown text={text} /></div>
      </div>}
    </div>;
  }

  const label = thoughtMs > 0 ? fill(t("work_trace.thought_for"), { duration: traceDuration(thoughtMs) }) : t("work_trace.thought");
  return <div data-testid="chat-thought" className="min-w-0">
    <button type="button" aria-expanded={open} disabled={!text} onClick={() => setOpen((value) => !value)} data-testid="chat-thought-toggle"
      className="inline-flex h-7 items-center gap-1 rounded-md text-sm text-muted-foreground transition-colors hover:text-foreground disabled:cursor-default disabled:hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="tabular-nums">{label}</span>
      {text && <ChevronRight aria-hidden className={cn("h-3.5 w-3.5 transition-transform duration-150", open && "rotate-90")} />}
    </button>
    {open && text && <div data-testid="chat-thought-body" className={cn(BODY, "mb-1 mt-1 max-h-96 overflow-y-auto scrollbar-jarvis")}>
      <ChatMarkdown text={text} />
    </div>}
  </div>;
}
