/**
 * The still mark for a shader pet. No three.js import: the agent dialog
 * and every grid tile use this, and a live canvas stays on the selected card.
 */
import { cn } from "@/lib/utils";

export function ShaderPetMark({ className }: { className?: string }) {
  return (
    <span
      data-testid="shader-pet-mark"
      aria-hidden
      className={cn(
        "block rounded-full bg-[radial-gradient(circle_at_35%_30%,#d7fbff,#3d7cff_42%,#12081f_74%)]",
        className ?? "h-16 w-16",
      )}
    />
  );
}
