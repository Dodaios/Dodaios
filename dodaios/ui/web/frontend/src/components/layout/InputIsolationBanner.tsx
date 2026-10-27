import { useState } from "react";
import { KeyboardOff, Loader2, X } from "lucide-react";
import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useInputIsolation } from "@/hooks/useInputIsolation";

/**
 * App-wide alert: outside input software cannot type into this window.
 *
 * Dictation and voice-typing apps, OS accessibility voice control, text
 * expanders, clipboard managers, and password-manager auto-type all inject
 * synthetic keystrokes into the focused window. Windows blocks that for any
 * window owned by a higher-integrity process, so while the app runs elevated
 * they appear to do nothing here while working in every other app — and neither
 * side reports an error, which is precisely what makes it undiagnosable from the
 * outside (live report 2026-07-25: "dictation just doesn't work in the Jarvis
 * window").
 *
 * Renders nothing whenever the window is reachable, which is the normal case on
 * every platform — including when the privilege state could not be read at all
 * (we never nag on a guess), and on accounts whose whole desktop runs elevated,
 * where nothing is isolated (the backend checks the shell's level too).
 *
 * Kept quiet on purpose: one small line, the long explanation in a tooltip, and
 * a dismissal that is remembered, so a user who closed it never sees it again.
 */

const DISMISS_KEY = "dodaios.inputIsolation.dismissed";

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberDismissed() {
  try {
    window.localStorage.setItem(DISMISS_KEY, "1");
  } catch {
    // Storage blocked: the notice just stays hidden for this session.
  }
}

export function InputIsolationBanner() {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const { report } = useInputIsolation();
  const [dismissed, setDismissed] = useState(readDismissed);
  const [restarting, setRestarting] = useState(false);

  if (!report?.blocked || dismissed) return null;

  async function restartUnelevated() {
    if (restarting) return;
    setRestarting(true);
    try {
      const response = await fetch("/api/settings/restart-unelevated", {
        method: "POST",
      });
      if (response.ok) return; // the window closes and comes back unelevated
      const body = await response.json().catch(() => null);
      const error = body?.detail?.error;
      if (error === "missions_running") {
        pushToast("warning", t("topbar.restart_missions_running"));
      } else if (error === "deescalation_failed") {
        // Honest failure: the app is still up and still elevated.
        pushToast("error", body?.detail?.message ?? t("input_isolation.restart_failed"));
      } else {
        pushToast("error", t("input_isolation.restart_failed"));
      }
    } catch {
      pushToast("error", t("input_isolation.restart_failed"));
    }
    setRestarting(false);
  }

  const details = report.can_restart_unelevated
    ? t("input_isolation.impact")
    : `${t("input_isolation.impact")} ${t("input_isolation.manual_hint")}`;

  return (
    <div
      data-testid="input-isolation-banner"
      data-reason={report.reason}
      role="status"
      title={details}
      className="flex items-center gap-2 px-4 py-1 text-meta text-muted-foreground"
    >
      <KeyboardOff className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{t("input_isolation.title")}</span>
      {report.can_restart_unelevated && (
        <button
          type="button"
          disabled={restarting}
          onClick={() => void restartUnelevated()}
          className="inline-flex shrink-0 items-center gap-1 text-foreground underline-offset-2 hover:underline disabled:opacity-60"
        >
          {restarting && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
          {t(restarting ? "input_isolation.restarting" : "input_isolation.restart_now")}
        </button>
      )}
      <button
        type="button"
        className="shrink-0 rounded p-0.5 hover:text-foreground"
        aria-label={t("input_isolation.dismiss")}
        title={t("input_isolation.dismiss")}
        onClick={() => {
          rememberDismissed();
          setDismissed(true);
        }}
      >
        <X className="h-3 w-3" aria-hidden />
      </button>
    </div>
  );
}
