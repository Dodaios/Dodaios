/**
 * The "Use a free local model" button and its one progress line.
 *
 * Lives in three places with one behaviour: the setup window's Connect step,
 * the first conversation (when nothing can answer yet) and the composer's
 * model picker. One click checks this computer, installs Ollama if it is
 * missing, downloads the model that fits and makes it the brain; the line
 * under the button says which of those it is doing, with a bar while
 * something downloads. A failure says why in one sentence and offers to try
 * again; a second try resumes the download where it stopped.
 */
import { Check, Cpu, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { stepPercent, type QuickstartPlan, type QuickstartStep } from "./localQuickstart";
import { useLocalQuickstart } from "./useLocalQuickstart";

export function quickstartLine(step: QuickstartStep, t: (key: string) => string): string {
  switch (step.phase) {
    case "checking":
      return t("first_run.local_model.checking");
    case "installing":
      return t("first_run.local_model.installing");
    case "starting":
      return t("first_run.local_model.starting");
    case "downloading":
      return fill(t("first_run.local_model.downloading"), {
        model: step.plan.label,
        size: step.plan.size_gb ? `${step.plan.size_gb.toFixed(1)} GB` : "",
      }).replace(/\s*\(\)/, "");
    case "selecting":
      return fill(t("first_run.local_model.selecting"), { model: step.plan.label });
    case "done":
      return fill(t("first_run.local_model.done"), { model: step.plan.label });
    case "error":
      return errorLine(step, t);
  }
}

function errorLine(step: Extract<QuickstartStep, { phase: "error" }>, t: (key: string) => string): string {
  const reasonKey: Record<typeof step.reason, string> = {
    remote: "first_run.local_model.error_remote",
    install: "first_run.local_model.error_install",
    start: "first_run.local_model.error_start",
    no_model: "first_run.local_model.error_no_model",
    download: "first_run.local_model.error_download",
    select: "first_run.local_model.error_select",
    unknown: "first_run.local_model.error_unknown",
  };
  const head = t(reasonKey[step.reason]);
  return step.detail ? `${head} ${step.detail}` : head;
}

export function LocalModelQuickstart({
  onReady,
  compact = false,
  className,
}: {
  /** Called once the model answers as the brain. */
  onReady?: (plan: QuickstartPlan) => void;
  /** The picker's narrow panel: smaller type, no icon tile. */
  compact?: boolean;
  className?: string;
}) {
  const ready = useLocaleChunk("onboarding");
  const t = useT();
  const { step, run, busy } = useLocalQuickstart(onReady);
  if (!ready) return null;

  const percent = stepPercent(step);
  const done = step?.phase === "done";
  const failed = step?.phase === "error";
  const plan = step && "plan" in step ? step.plan : null;

  return (
    <div
      data-testid="local-model-quickstart"
      data-phase={step?.phase ?? "idle"}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-border bg-sheen/[0.02]",
        compact ? "p-2.5" : "p-3",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        {!compact && (
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-secondary text-muted-foreground" aria-hidden>
            <Cpu className="h-4 w-4" />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("font-medium text-foreground", compact ? "text-xs" : "text-sm")}>
            {t("first_run.local_model.title")}
          </p>
          <p className={cn("text-muted-foreground", compact ? "text-[11px]" : "text-xs")}>
            {plan ? plan.reason || plan.hardware.summary : t("first_run.local_model.hint")}
          </p>
        </div>
        {done ? (
          <span className="inline-flex items-center gap-1 text-xs text-foreground" data-testid="local-model-ready">
            <Check className="h-3.5 w-3.5" aria-hidden />
            {t("first_run.local_model.ready")}
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant={failed ? "outline" : "default"}
            onClick={run}
            disabled={busy}
            data-testid="local-model-quickstart-run"
            className="shrink-0"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : failed ? (
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            ) : null}
            {failed ? t("first_run.local_model.retry") : t("first_run.local_model.action")}
          </Button>
        )}
      </div>
      {step && (
        <div className="space-y-1.5" aria-live="polite">
          {percent !== null && !done && (
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
              aria-label={t("first_run.local_model.progress")}
              className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
            >
              <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${percent}%` }} />
            </div>
          )}
          <p
            data-testid="local-model-quickstart-line"
            className={cn("text-xs", failed ? "text-destructive" : "text-muted-foreground")}
          >
            {quickstartLine(step, t)}
            {percent !== null && !done && ` ${percent}%`}
          </p>
          {done && step.phase === "done" && step.probeFailed && (
            <p className="text-xs text-muted-foreground">{t("first_run.local_model.first_answer_slow")}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default LocalModelQuickstart;
