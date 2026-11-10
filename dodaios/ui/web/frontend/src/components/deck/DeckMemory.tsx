/**
 * The Command Deck's memory card: what the assistant carries into every
 * conversation right now, read from the personal memory vault (ADR-0044).
 * Opening it goes to the Memory section.
 */
import { Brain } from "lucide-react";
import { DeckCard } from "@/components/deck/DeckCard";
import { useLocaleChunk, useT } from "@/i18n";
import { useVaultOverview } from "@/lib/personalMemoryApi";
import { useEventStore } from "@/store/events";

/** The always-on block, as plain lines: section headings and their memories. */
export function inMindLines(block: string): Array<{ heading: boolean; text: string }> {
  return block
    .split("\n")
    .slice(2) // the block's own two-line header
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) =>
      line.startsWith("- ")
        ? { heading: false, text: line.slice(2) }
        : { heading: true, text: line.replace(/:$/, "") },
    );
}

export function MemoryCard({ className }: { className?: string }) {
  const t = useT();
  useLocaleChunk("memory");
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const overview = useVaultOverview();
  const lines = inMindLines(overview.data?.prompt_block ?? "");

  return (
    <DeckCard
      icon={Brain}
      title={t("vault.title")}
      meta={overview.data ? String(overview.data.stats.current) : undefined}
      variant="bracket"
      onOpen={() => setActiveSection("memory")}
      openLabel={t("deck.open_section")}
      className={className}
      bodyClassName="min-h-0 overflow-y-auto px-2.5 py-2"
    >
      {lines.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {overview.isLoading ? "…" : t("vault.always_empty")}
        </p>
      ) : (
        <ul className="space-y-1" data-testid="deck-memory-lines">
          {lines.map((line, index) =>
            line.heading ? (
              <li
                key={`${index}-${line.text}`}
                className="pt-1.5 font-mono text-micro uppercase tracking-[0.18em] text-muted-foreground first:pt-0"
              >
                {line.text}
              </li>
            ) : (
              <li key={`${index}-${line.text}`} className="line-clamp-2 text-xs leading-snug text-foreground">
                {line.text}
              </li>
            ),
          )}
        </ul>
      )}
    </DeckCard>
  );
}
