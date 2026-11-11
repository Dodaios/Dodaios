/**
 * The still mark for the scene orb. No three.js import: every grid tile
 * uses this, and the live canvas stays on the selected card.
 */
import { cn } from "@/lib/utils";

export function JarvisOrbMark({ className }: { className?: string }) {
  return (
    <span
      data-testid="jarvis-orb-mark"
      aria-hidden
      className={cn(
        "relative block rounded-full bg-[radial-gradient(circle_at_40%_35%,#f4ffff,#38f4ff_28%,#0b6f9a_58%,transparent_72%)]",
        className ?? "h-16 w-16",
      )}
    >
      <span className="absolute inset-[18%] rounded-full border border-cyan-200/70" />
      <span className="absolute inset-[6%] rotate-45 rounded-full border border-cyan-100/40" />
    </span>
  );
}
