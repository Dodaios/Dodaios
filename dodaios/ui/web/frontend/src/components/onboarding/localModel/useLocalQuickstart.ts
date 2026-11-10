import { useCallback, useEffect, useRef, useState } from "react";
import { QuickstartError, runLocalQuickstart, type QuickstartPlan, type QuickstartStep } from "./localQuickstart";

/**
 * The React side of "Use a free local model": one run at a time, the current
 * step in state for the progress line, nothing written after unmount, and
 * `onReady` called once with the model when the run ends well.
 */
export function useLocalQuickstart(onReady?: (plan: QuickstartPlan) => void) {
  const [step, setStep] = useState<QuickstartStep | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(() => {
    if (running.current) return;
    running.current = true;
    const alive = () => mounted.current;
    const report = (next: QuickstartStep) => {
      if (mounted.current) setStep(next);
    };
    void (async () => {
      try {
        const plan = await runLocalQuickstart({ report, alive });
        if (plan && mounted.current) readyRef.current?.(plan);
      } catch (err) {
        report(
          err instanceof QuickstartError
            ? { phase: "error", reason: err.reason, detail: err.message }
            : { phase: "error", reason: "unknown", detail: err instanceof Error ? err.message : String(err) },
        );
      } finally {
        running.current = false;
      }
    })();
  }, []);

  const busy = step !== null && step.phase !== "done" && step.phase !== "error";
  return { step, run, busy };
}
