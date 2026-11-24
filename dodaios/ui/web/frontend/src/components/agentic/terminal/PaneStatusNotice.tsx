import { RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { PANE_BRAND, type TerminalAppearance } from "../terminalThemes";
import { fill, useT } from "@/i18n";
import { PaneStatus } from "./paneShared";

const NOTICE_TONE: Record<
  "warning" | "error",
  Record<TerminalAppearance, { border: string; text: string }>
> = {
  warning: {
    light: { border: "rgba(165,122,29,0.85)", text: "#a57a1d" },
    dark: { border: "rgba(214,169,74,0.85)", text: "#d6a94a" },
  },
  error: {
    light: { border: "rgba(199,46,35,0.9)", text: "#c72e23" },
    dark: { border: "rgba(232,87,76,0.9)", text: "#e8574c" },
  },
};

/**
 * What went wrong in this pane, and the one way out of it.
 *
 * ## Why a row of its own rather than a badge
 *
 * Both halves of this used to be somewhere else, and neither survived being
 * there. The reason was written INTO the terminal — an exit banner, or one
 * trouble line per kind of trouble (see `troubleShown`) — where the next thing
 * the pane draws scrolls it away and nothing brings it back; a user returning
 * to a dead pane found a still screen and no sentence explaining it. The way
 * out was a small button in the header, in the cluster that hides until the
 * pane is hovered or focused, competing for width with five others.
 *
 * A dead pane can afford the height. Its terminal is not being drawn into any
 * more, so the ~24 px this costs comes out of a static screen — and it buys the
 * two things that pane owes the user: what happened, and what to press.
 *
 * ## Why the live states show nothing
 *
 * `connecting` and `live` are answered better elsewhere and answered already:
 * the starting overlay covers a pane that has not painted yet, and the badge in
 * the header carries the state for anyone who looks. A standing strip for them
 * would take a row off every healthy pane in the workspace to say "fine".
 */
export function PaneStatusNotice({
  name,
  displayName,
  status,
  detail,
  light,
  onRestart,
}: {
  name: string;
  displayName: string;
  status: PaneStatus;
  detail?: string;
  light: boolean;
  onRestart?: () => void;
}) {
  const t = useT();
  if (status !== "exited" && status !== "error") return null;
  const appearance: TerminalAppearance = light ? "light" : "dark";
  const tone = NOTICE_TONE[status === "error" ? "error" : "warning"][appearance];
  const brand = PANE_BRAND[appearance];
  /*
   * The two details are written for different sentences and cannot be shown the
   * same way. A trouble message is already one ("This terminal is no longer part
   * of the open workspace."); an exit reason is a CLAUSE — `explainExit` returns
   * "stopped", or "stopped unexpectedly (exit code 2) — use Restart to bring it
   * back" — which needs the agent's name in front of it to be a sentence at all.
   * Shown raw, a dead pane said nothing but "stopped".
   */
  const message =
    status === "error"
      ? detail || fill(t("agentic_grid.pane.unreachable"), { pane: name })
      : detail
        ? fill(t("agentic_grid.pane.exited_detail"), { agent: displayName, detail })
        : fill(t("agentic_grid.pane.exited"), { agent: displayName, pane: name });
  return (
    <div
      data-testid={`pane-notice-${name}`}
      data-tone={status === "error" ? "error" : "warning"}
      // Announced once, quietly. `polite` rather than `assertive`: a pane going
      // quiet is news, but it is never more urgent than the sentence a screen
      // reader is in the middle of.
      role="status"
      aria-live="polite"
      // The shared section's notice shape — a rule down the left edge, no fill,
      // no icon — one size down for a pane header's scale. A filled box here
      // would read as a second, louder terminal sitting on top of the first.
      className="flex shrink-0 items-center gap-2 border-l-2 px-2 py-1 text-micro"
      style={
        {
          borderColor: tone.border,
          color: tone.text,
          // The pane's ladder, published here as well as on the header: this
          // strip is a sibling of the header, not a child, so the Restart
          // button below cannot inherit the header's copy.
          "--pane-accent": brand.accent,
          "--pane-ink": brand.ink,
          "--pane-chip": brand.chip,
          "--pane-accent-soft": brand.accentSoft,
        } as React.CSSProperties
      }
    >
      <span className="min-w-0 flex-1 truncate" title={message}>
        {message}
      </span>
      {onRestart && (
        <button
          type="button"
          aria-label={fill(t("agentic_grid.pane.restart_aria"), { pane: name })}
          title={fill(t("agentic_grid.pane.restart_title"), { agent: displayName, pane: name })}
          data-testid={`pane-restart-${name}`}
          onClick={(e) => {
            e.stopPropagation();
            onRestart();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className={cn(
            // The pane's own secondary button: a real lift fill with the
            // pane's ink on it. It used to be `--primary` at 20 % with
            // `--primary` as the label — an opacity standing in for a surface,
            // and a fill used as an ink. Both land wrong when the pane's
            // appearance and the app's theme disagree.
            "flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5",
            "bg-[color:var(--pane-chip)] text-micro font-medium text-[color:var(--pane-ink)]",
            "transition-colors duration-150 hover:bg-[color:var(--pane-accent-soft)]",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--pane-accent)]",
          )}
        >
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
          {t("agentic_grid.pane.restart")}
        </button>
      )}
    </div>
  );
}

/*
 * The pane badge used to live here and reported the SOCKET: "live" for any pane
 * with a working pipe, which is nearly all of them nearly all of the time. It
 * moved to ./PaneActivityPill, which answers the question people were actually
 * reading it for — is this agent still working — and still reports the pipe in
 * the three cases where the pipe is the news.
 */
