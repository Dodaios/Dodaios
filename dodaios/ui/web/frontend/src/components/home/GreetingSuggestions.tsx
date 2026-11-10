import { useEffect, useMemo, useState } from "react";
import { CalendarClock, MessageCircle } from "lucide-react";

import { useT } from "@/i18n";
import { useSocietyRoster } from "@/components/society/data";
import { writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { useAgentChatStore } from "@/store/agentChat";
import { buildSuggestions, type DueItem } from "@/components/home/suggestionPicks";

/** "Soon" for the greeting: the coming three days. */
const DUE_DAYS = 3;

/** Put the caret at the end of the front page's composer. */
function focusComposer(): void {
  const field = [...document.querySelectorAll<HTMLElement>("[data-jarvis-chat-input]")]
    .find((node) => node.isContentEditable && node.offsetParent !== null);
  if (!field) return;
  field.focus();
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(field);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

/**
 * Two or three quiet chips under the greeting on the empty front page, from
 * what falls due soon and the agents at work (components/home/
 * suggestionPicks). Nothing shows when there is nothing to offer, so a
 * quiet day keeps the page to the greeting alone. A chip fills the composer;
 * it never sends.
 */
export default function GreetingSuggestions() {
  const t = useT();
  const [due, setDue] = useState<DueItem[]>([]);
  const roster = useSocietyRoster();

  useEffect(() => {
    let live = true;
    void fetch(`/api/memory/vault/upcoming?days=${DUE_DAYS}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(
        (body: { items?: DueItem[] } | null) => { if (live && Array.isArray(body?.items)) setDue(body.items); },
        // Offline or no memory yet: the greeting simply stands alone.
        () => undefined,
      );
    return () => { live = false; };
  }, []);

  const agents = useMemo(
    () => (roster.data && !roster.data.sample
      ? roster.data.agents.filter((a) => a.tier !== "lead" && a.lifecycle !== "archived")
      : []),
    [roster.data],
  );
  const suggestions = useMemo(() => buildSuggestions(due, agents, t), [due, agents, t]);
  if (suggestions.length === 0) return null;

  const pick = (text: string) => {
    const sessionId = useAgentChatStore.getState().activeSessionId;
    writeComposerDraft(useAgentChatStore, sessionId, { text, choices: [] });
    window.requestAnimationFrame(() => window.requestAnimationFrame(focusComposer));
  };

  return (
    <ul
      aria-label={t("design.greeting.suggestions")}
      data-testid="greeting-suggestions"
      className="mt-6 flex w-full max-w-reading flex-wrap justify-center gap-2 animate-in fade-in-0 slide-in-from-bottom-1 duration-base"
    >
      {suggestions.map((s) => {
        const Icon = s.kind === "due" ? CalendarClock : MessageCircle;
        return (
          <li key={s.id} className="min-w-0 max-w-full">
            <button
              type="button"
              data-testid="greeting-suggestion"
              data-kind={s.kind}
              onClick={() => pick(s.text)}
              className="flex min-h-9 max-w-full items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-left text-base text-foreground-secondary shadow-rim transition-colors duration-fast hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Icon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 truncate">{s.text}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
