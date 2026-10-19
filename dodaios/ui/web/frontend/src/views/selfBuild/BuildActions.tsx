/**
 * The actions that apply to a build right now, and nothing else.
 *
 * Proposed: build it / not this. On trial: keep / undo. Kept: undo. Archived:
 * restore / undo. Undo is one click with no "are you sure": the promise of a
 * trial is that taking it back costs nothing.
 */
import { Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { BuildAction } from "@/hooks/useSelfBuild";
import type { Build } from "@/lib/selfBuildApi";

export type ActionHandler = (build: Build, action: BuildAction) => void;

interface Choice {
  action: BuildAction;
  label: string;
  primary: boolean;
  disabled?: boolean;
  title?: string;
}

export function choicesFor(
  build: Build,
  canBuild: boolean,
  t: (key: string) => string,
  blockedTitle?: string,
): Choice[] {
  switch (build.state) {
    case "proposed":
      return [
        {
          action: "accept",
          label: t("self_build.action.accept"),
          primary: true,
          disabled: !canBuild,
          title: canBuild ? undefined : blockedTitle ?? t("self_build.no_builder"),
        },
        { action: "undo", label: t("self_build.action.reject"), primary: false },
      ];
    case "trial":
      return [
        { action: "keep", label: t("self_build.action.keep"), primary: true },
        { action: "undo", label: t("self_build.action.undo"), primary: false },
      ];
    case "kept":
      return [{ action: "undo", label: t("self_build.action.undo"), primary: false }];
    case "archived":
      return [
        { action: "keep", label: t("self_build.action.restore"), primary: false },
        { action: "undo", label: t("self_build.action.undo"), primary: false },
      ];
    case "building":
    case "proving":
      return [{ action: "undo", label: t("self_build.action.undo"), primary: false }];
    default:
      return [];
  }
}

export function BuildActions({
  build,
  canBuild,
  blockedTitle,
  busy,
  onAction,
  size = "sm",
}: {
  build: Build;
  canBuild: boolean;
  blockedTitle?: string;
  busy: boolean;
  onAction: ActionHandler;
  size?: "sm" | "default";
}) {
  const t = useT();
  const choices = choicesFor(build, canBuild, t, blockedTitle);
  if (!choices.length) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5" data-testid="build-actions">
      {choices.map((choice) => (
        <button
          key={choice.action}
          type="button"
          data-testid={`build-${choice.action}`}
          disabled={busy || choice.disabled}
          title={choice.title}
          onClick={(event) => {
            event.stopPropagation();
            onAction(build, choice.action);
          }}
          className={cn(
            "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
            size === "sm" ? "h-7 px-2.5 text-sm" : "h-8 px-3 text-sm",
            choice.primary
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "border border-border-strong text-foreground hover:bg-secondary",
          )}
        >
          {busy && choice.primary && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
          {choice.label}
        </button>
      ))}
    </div>
  );
}
