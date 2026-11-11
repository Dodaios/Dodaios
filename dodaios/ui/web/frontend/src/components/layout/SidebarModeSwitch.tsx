import type { ReactNode } from "react";
import { CodeIcon } from "@/components/icons/sectionIcons";
import { PetMark } from "@/components/pets/PetMark";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** The app's two places. */
export type SidebarMode = "dodaios" | "ide";

const SEGMENT =
  "flex h-7 min-w-0 items-center justify-center gap-1.5 rounded text-sm font-medium transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const SEGMENT_ON = "bg-background text-foreground-strong shadow-rim";
const SEGMENT_OFF = "text-muted-foreground hover:text-foreground";

/**
 * The switch at the top of the sidebar: the conversation with the assistant
 * on one side, the Agentic IDE on the other. Those two are the whole app; a
 * Settings page lights neither half, and either half leads back out of it.
 *
 * The assistant's half carries the person's pet, because the pet is the
 * assistant's face, and `status` (the voice dot) at its end.
 */
export function SidebarModeSwitch({
  mode,
  railed = false,
  onPick,
  status,
}: {
  /** The place on screen, or null while neither is. */
  mode: SidebarMode | null;
  /** Icons only, stacked: the sidebar is collapsed to its rail. */
  railed?: boolean;
  onPick: (mode: SidebarMode) => void;
  /** Drawn at the end of the assistant's half. */
  status?: ReactNode;
}) {
  const t = useT();
  const assistant = t("sidebar.conversation");
  const ide = t("nav.agentic_ide");
  return (
    <div
      role="radiogroup"
      aria-label={t("sidebar.mode_aria")}
      data-testid="sidebar-mode-switch"
      className={cn(
        "flex gap-0.5 rounded-md border border-border bg-secondary/60 p-0.5",
        railed ? "flex-col" : "w-full",
      )}
    >
      <button
        type="button"
        role="radio"
        aria-checked={mode === "dodaios"}
        aria-label={assistant}
        title={railed ? assistant : undefined}
        data-testid="sidebar-mode-dodaios"
        data-tour="new-chat"
        onClick={() => onPick("dodaios")}
        className={cn(SEGMENT, railed ? "w-9" : "flex-1 px-2", mode === "dodaios" ? SEGMENT_ON : SEGMENT_OFF)}
      >
        <span data-testid="sidebar-style-avatar" className="relative h-4 w-4 shrink-0">
          <PetMark size={16} reactive />
        </span>
        {!railed && <span className="truncate">{assistant}</span>}
        {!railed && status}
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={mode === "ide"}
        aria-label={ide}
        title={ide}
        data-testid="sidebar-mode-ide"
        data-tour="nav-agentic-ide"
        onClick={() => onPick("ide")}
        className={cn(SEGMENT, railed ? "w-9" : "flex-1 px-2", mode === "ide" ? SEGMENT_ON : SEGMENT_OFF)}
      >
        <CodeIcon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0" />
        {!railed && <span className="truncate">{t("sidebar.mode_ide")}</span>}
      </button>
    </div>
  );
}
