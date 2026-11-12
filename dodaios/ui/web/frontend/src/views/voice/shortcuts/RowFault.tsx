import type { ReactNode } from "react";
import { CircleAlert } from "lucide-react";

/**
 * One sentence about what is wrong with the row or field it stands at.
 *
 * Body ink, like every other sentence in the section; the hue is on the glyph
 * only. It goes into a row's `below` slot, directly under the control it is
 * about.
 */
export function RowFault({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p role="alert" className="flex items-center gap-row text-body text-foreground" data-testid={testId}>
      <CircleAlert aria-hidden="true" className="h-4 w-4 shrink-0 text-destructive" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
