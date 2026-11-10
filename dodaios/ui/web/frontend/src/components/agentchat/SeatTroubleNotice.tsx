import { useEventStore, type SectionId } from "@/store/events";
import type { NoticeItem } from "./reduce";

type Fix = { label: string; section: SectionId };

function fixesOf(item: NoticeItem): Fix[] {
  const raw = Array.isArray(item.data.fixes) ? item.data.fixes : [];
  return raw
    .map((row) => row as Record<string, unknown>)
    .filter((row) => typeof row.label === "string" && typeof row.section === "string")
    .map((row) => ({ label: String(row.label), section: String(row.section) as SectionId }));
}

/**
 * One written notice when an agent's model seat failed the same way several
 * times in a row (agent_chat/seat_outcomes.py): the cause, and a button per
 * fix path that opens the screen where it is fixed. Nothing is switched for
 * the person and it is never spoken.
 */
export function SeatTroubleNotice({ item }: { item: NoticeItem }) {
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const fixes = fixesOf(item);
  return (
    <div data-message-id={item.id} data-testid="seat-trouble" role="alert"
      className="mx-auto flex max-w-[85%] flex-col gap-2 rounded-lg bg-card px-4 py-3 text-body">
      <span className="text-muted-foreground">{item.text}</span>
      {fixes.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {fixes.map((fix) => (
            <button key={fix.section + fix.label} type="button" data-testid="seat-trouble-fix"
              onClick={() => setActiveSection(fix.section)}
              className="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {fix.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
