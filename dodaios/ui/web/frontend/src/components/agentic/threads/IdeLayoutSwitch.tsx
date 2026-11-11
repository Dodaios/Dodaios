import { LayoutGrid, MessagesSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import {
  CAPTION_ICON_CLASS, CAPTION_ICON_STROKE, CAPTION_SEGMENT, CAPTION_SEGMENT_OFF, CAPTION_SEGMENT_ON,
  CAPTION_SEGMENT_PX as SEGMENT_PX, CAPTION_THUMB, CAPTION_TRACK,
} from "@/components/layout/captionSwitch";
import { useIdeThreadsStore, type IdeLayout } from "@/store/ideThreads";

/** `labelKey` is a locale key, translated where the switch renders. */
const CHOICES: { choice: IdeLayout; labelKey: string; Icon: typeof LayoutGrid }[] = [
  { choice: "grid", labelKey: "ide_threads.layout_grid", Icon: LayoutGrid },
  { choice: "threads", labelKey: "ide_threads.layout_threads", Icon: MessagesSquare },
];

/**
 * Grid or threads — the two faces of the Agentic IDE. Sits in the middle of
 * the window caption: a rounded track with one thumb that slides under the
 * face that is on. Separate buttons rather than one that cycles, so each says
 * where it leads.
 */
export function IdeLayoutSwitch({ className }: { className?: string }) {
  const t = useT();
  const layout = useIdeThreadsStore((state) => state.layout);
  const setLayout = useIdeThreadsStore((state) => state.setLayout);
  const index = Math.max(0, CHOICES.findIndex((item) => item.choice === layout));

  return <div role="radiogroup" aria-label={t("ide_threads.layout_aria")} data-testid="ide-layout-switch"
    className={cn(CAPTION_TRACK, className)}>
    <span aria-hidden
      style={{ width: SEGMENT_PX, transform: `translateX(${index * SEGMENT_PX}px)` }}
      className={CAPTION_THUMB} />
    {CHOICES.map(({ choice, labelKey, Icon }) => { const label = t(labelKey); return <button key={choice} type="button" role="radio"
      data-testid={`ide-layout-${choice}`} aria-checked={layout === choice} aria-label={label} title={label}
      onClick={() => setLayout(choice)}
      style={{ width: SEGMENT_PX }}
      className={cn(CAPTION_SEGMENT, layout === choice ? CAPTION_SEGMENT_ON : CAPTION_SEGMENT_OFF)}>
      <Icon aria-hidden className={CAPTION_ICON_CLASS} strokeWidth={CAPTION_ICON_STROKE} />
    </button>; })}
  </div>;
}
