import { Loader2 } from "lucide-react";
import { CodeIcon } from "@/components/icons/sectionIcons";
import { PetMark } from "@/components/pets/PetMark";
import { CAPTION_SEGMENT, CAPTION_SEGMENT_OFF, CAPTION_SEGMENT_ON, CAPTION_THUMB, CAPTION_TRACK } from "@/components/layout/captionSwitch";
import { useVoiceIndicator } from "@/hooks/useVoiceIndicator";
import { useT } from "@/i18n";
import { IDE_SECTIONS } from "@/lib/ideSections";
import { startNewTextChat } from "@/lib/newChat";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/** The app's two places. */
export type AppSurface = "dodaios" | "ide";

/**
 * The switch in the middle of the window caption: the conversation with the
 * assistant on one side, the Agentic IDE on the other. Those two are the whole
 * app; a Settings page lights neither half, and either half leads back out.
 *
 * It sits in the caption rather than atop the sidebar because it is the
 * widest choice on screen: which app you are in. The sidebar below it then
 * belongs to that place alone (the IDE puts its grid / chat switch there).
 *
 * The assistant's half carries the person's pet, because the pet is the
 * assistant's face, and the voice dot at its end. Both halves are one width
 * (a two-column grid), so the thumb slides by exactly one column.
 */
export function AppSurfaceSwitch({ className }: { className?: string }) {
  const t = useT();
  const active = useEventStore((s) => s.activeSection);
  const setActive = useEventStore((s) => s.setActiveSection);
  const voice = useVoiceIndicator();
  const surface: AppSurface | null = IDE_SECTIONS.includes(active) ? "ide" : active === "chats" ? "dodaios" : null;
  const assistant = t("sidebar.conversation");
  const ide = t("nav.agentic_ide");

  const pick = (next: AppSurface) => {
    if (next === "ide") { setActive("agentic-ide"); return; }
    startNewTextChat();
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("sidebar.mode_aria")}
      data-testid="surface-switch"
      className={cn(CAPTION_TRACK, "grid grid-cols-2", className)}
    >
      {surface && (
        <span
          aria-hidden
          data-testid="surface-switch-thumb"
          style={{ width: "calc(50% - 3px)", transform: surface === "ide" ? "translateX(100%)" : undefined }}
          className={CAPTION_THUMB}
        />
      )}
      <button
        type="button"
        role="radio"
        aria-checked={surface === "dodaios"}
        aria-label={assistant}
        title={assistant}
        data-testid="surface-dodaios"
        data-tour="new-chat"
        onClick={() => pick("dodaios")}
        className={cn(CAPTION_SEGMENT, "gap-1.5 px-3 text-sm font-medium", surface === "dodaios" ? CAPTION_SEGMENT_ON : CAPTION_SEGMENT_OFF)}
      >
        <span data-testid="surface-pet" className="relative h-4 w-4 shrink-0">
          <PetMark size={16} reactive />
        </span>
        <span className="truncate">{assistant}</span>
        {voice.spinning ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" data-testid="voice-starting-spinner" aria-hidden />
        ) : (
          <span data-testid="surface-voice-dot" role="img" aria-label={voice.label} title={voice.label}
            className={cn("h-1.5 w-1.5 shrink-0 rounded-full", voice.dot, voice.pulse && "animate-jarvis-pulse")} />
        )}
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={surface === "ide"}
        aria-label={ide}
        title={ide}
        data-testid="surface-ide"
        data-tour="nav-agentic-ide"
        onClick={() => pick("ide")}
        className={cn(CAPTION_SEGMENT, "gap-1.5 px-3 text-sm font-medium", surface === "ide" ? CAPTION_SEGMENT_ON : CAPTION_SEGMENT_OFF)}
      >
        <CodeIcon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0" />
        <span className="truncate">{t("sidebar.mode_ide")}</span>
      </button>
    </div>
  );
}
