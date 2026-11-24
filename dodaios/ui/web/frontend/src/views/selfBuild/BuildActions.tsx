/**
 * The one action a build offers the person: Undo.
 *
 * Nothing asks for an OK and nothing is kept on a click: a build goes live on
 * trial when it can be undone, and its use decides whether it is kept or
 * archived (docs/self-build.md). Undo is one click with no "are you sure": the
 * promise of a trial is that taking it back costs nothing. An archived build
 * offers it only when it made something.
 */
import { Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Build } from "@/lib/selfBuildApi";

export type UndoHandler = (build: Build) => void;

/** Whether a build in this state has something an undo would take away. */
export function canUndo(build: Build): boolean {
  switch (build.state) {
    case "building":
    case "proving":
    case "trial":
    case "kept":
      return true;
    case "archived":
      return Boolean(build.artefact?.type);
    default:
      return false;
  }
}

export function BuildActions({
  build,
  busy,
  onUndo,
  size = "sm",
}: {
  build: Build;
  busy: boolean;
  onUndo: UndoHandler;
  size?: "sm" | "default";
}) {
  const t = useT();
  if (!canUndo(build)) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5" data-testid="build-actions">
      <button
        type="button"
        data-testid="build-undo"
        disabled={busy}
        onClick={(event) => {
          event.stopPropagation();
          onUndo(build);
        }}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 rounded-md border border-border-strong font-medium text-foreground transition-colors hover:bg-secondary",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-7 px-2.5 text-sm" : "h-8 px-3 text-sm",
        )}
      >
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
        {t("self_build.action.undo")}
      </button>
    </div>
  );
}
