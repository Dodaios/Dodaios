import { useEffect, useRef, useState } from "react";
import { sameStep, stepKey, type Activity } from "./activityModel";

/** No step leaves the line sooner than this, however fast the next one arrives. */
export const HOLD_MS = 800;

/**
 * Paces the activity line so it reads instead of flickering.
 *
 * - A shown step stays at least `holdMs`. A newer step waits in a one-slot
 *   queue meanwhile; only the latest waiting step is kept, so a burst of
 *   ten short calls costs one change, not ten.
 * - A step of the same family and target as the shown one is the same step
 *   (`sameStep`): the line keeps its words and does not animate again.
 *
 * The line therefore changes at most once per `holdMs`, and the component
 * re-renders only when it does.
 */
export function usePacedActivity(next: Activity | null, holdMs = HOLD_MS): Activity | null {
  const [shown, setShown] = useState<Activity | null>(next);
  const shownAt = useRef(Date.now());
  const latest = useRef(next);
  latest.current = next;
  const shownRef = useRef(shown);
  shownRef.current = shown;
  const key = stepKey(next);

  useEffect(() => {
    if (sameStep(shownRef.current, latest.current)) return;
    const show = () => {
      const pending = latest.current;
      if (sameStep(shownRef.current, pending)) return;
      shownAt.current = Date.now();
      setShown(pending);
    };
    const wait = holdMs - (Date.now() - shownAt.current);
    if (wait <= 0) {
      show();
      return;
    }
    const timer = window.setTimeout(show, wait);
    return () => window.clearTimeout(timer);
  }, [key, shown, holdMs]);

  return shown;
}
