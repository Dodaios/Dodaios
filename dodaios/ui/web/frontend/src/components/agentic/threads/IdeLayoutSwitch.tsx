import { LayoutGrid, MessagesSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { useIdeThreadsStore, type IdeLayout } from "@/store/ideThreads";

/**
 * Chat first: it is the face the IDE opens on. `labelKey` is the short word
 * shown in the switch, `titleKey` the full name for the tooltip and screen
 * readers; both are locale keys, translated where the switch renders.
 */
const CHOICES: { choice: IdeLayout; labelKey: string; titleKey: string; Icon: typeof LayoutGrid }[] = [
  { choice: "threads", labelKey: "ide_threads.layout_chat_short", titleKey: "ide_threads.layout_threads", Icon: MessagesSquare },
  { choice: "grid", labelKey: "ide_threads.layout_grid_short", titleKey: "ide_threads.layout_grid", Icon: LayoutGrid },
];

const SEGMENT =
  "flex h-7 min-w-0 items-center justify-center gap-1.5 rounded text-sm font-medium transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const SEGMENT_ON = "bg-background text-foreground-strong shadow-rim";
const SEGMENT_OFF = "text-muted-foreground hover:text-foreground";

/**
 * Chat or grid — the two faces of the Agentic IDE, at the top of the sidebar
 * while the IDE is on screen. The caption above picks the place (Dodaios or
 * IDE); this picks how the IDE reads. Separate buttons rather than one that
 * cycles, so each says where it leads. On the collapsed rail it stacks to
 * icons.
 */
export function IdeLayoutSwitch({ railed = false, className }: { railed?: boolean; className?: string }) {
  const t = useT();
  const layout = useIdeThreadsStore((state) => state.layout);
  const setLayout = useIdeThreadsStore((state) => state.setLayout);

  return <div role="radiogroup" aria-label={t("ide_threads.layout_aria")} data-testid="ide-layout-switch"
    className={cn("flex gap-0.5 rounded-md border border-border bg-secondary/60 p-0.5", railed ? "flex-col" : "w-full", className)}>
    {CHOICES.map(({ choice, labelKey, titleKey, Icon }) => {
      const title = t(titleKey);
      const on = layout === choice;
      return <button key={choice} type="button" role="radio"
        data-testid={`ide-layout-${choice}`} aria-checked={on} aria-label={title} title={title}
        onClick={() => setLayout(choice)}
        className={cn(SEGMENT, railed ? "w-9" : "flex-1 px-2", on ? SEGMENT_ON : SEGMENT_OFF)}>
        <Icon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0" />
        {!railed && <span className="truncate">{t(labelKey)}</span>}
      </button>;
    })}
  </div>;
}
