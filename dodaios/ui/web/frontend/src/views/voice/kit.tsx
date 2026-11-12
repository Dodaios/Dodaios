import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, CircleAlert, Search } from "lucide-react";

import { SkeletonBar } from "@/components/layout/PanelSkeleton";
import { cn } from "@/lib/utils";

/**
 * The building blocks of the Voice section.
 *
 * The section is a short column of grouped rows. A row is a label and one
 * control. Nothing explains itself in a second, smaller line: when a row needs
 * a sentence to be understood, the label is wrong.
 *
 * Type on these screens has four sizes and no more:
 *
 *   display  the one headline of the Dictation tab
 *   title    row labels, values, list text, buttons that carry a row
 *   reading  transcripts
 *   body     the smallest text there is: group titles, times, notices
 *
 * No smaller size, no badge and no capitalised label appears here;
 * `plain-type.test.ts` reads the section's source and fails on one.
 */

/** The scroll container and centred column every tab stands in. */
export function VoicePage({
  children,
  wide = false,
  testId,
}: {
  children: ReactNode;
  /** The reading measure, for a tab whose content is prose (transcripts). */
  wide?: boolean;
  testId?: string;
}) {
  return (
    <div className="h-full overflow-y-auto scrollbar-jarvis" data-testid={testId}>
      <div
        className={cn(
          "mx-auto flex w-full flex-col gap-group px-6 pb-16 pt-10",
          wide ? "max-w-reading" : "max-w-form",
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** A titled set of rows on one card. The title is optional. */
export function Group({
  title,
  action,
  children,
  testId,
}: {
  title?: string;
  /** One control beside the title, such as "Add". */
  action?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="flex flex-col gap-stack" data-testid={testId}>
      {(title || action) && (
        <div className="flex min-h-9 items-center justify-between gap-row px-1">
          {title ? (
            <h2 className="text-body font-medium text-muted-foreground">{title}</h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      )}
      <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card shadow-rim">
        {children}
      </div>
    </section>
  );
}

/**
 * One row of a group: a label on the left, one control on the right.
 *
 * `below` is for content the row opens (a key field, a test result), never for
 * a caption.
 */
export function Row({
  label,
  icon,
  children,
  below,
  htmlFor,
  testId,
  className,
}: {
  label: ReactNode;
  icon?: ReactNode;
  /** The control. */
  children?: ReactNode;
  below?: ReactNode;
  htmlFor?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <div className={cn("px-block", className)} data-testid={testId}>
      <div className="flex min-h-14 items-center justify-between gap-block py-2">
        <div className="flex min-w-0 items-center gap-stack">
          {icon && <span className="flex shrink-0 items-center text-foreground">{icon}</span>}
          {htmlFor ? (
            <label
              htmlFor={htmlFor}
              className="min-w-0 truncate text-title font-medium text-foreground-strong"
            >
              {label}
            </label>
          ) : (
            <span className="min-w-0 truncate text-title font-medium text-foreground-strong">
              {label}
            </span>
          )}
        </div>
        {children !== undefined && (
          <div className="flex shrink-0 items-center gap-row">{children}</div>
        )}
      </div>
      {below && <div className="pb-block">{below}</div>}
    </div>
  );
}

/** The value a row shows when it has no control of its own. */
export function RowValue({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <span className="text-title text-muted-foreground" data-testid={testId}>
      {children}
    </span>
  );
}

/** A key on a keyboard, at the size of the text beside it. */
export function Keycap({ children, large = false }: { children: ReactNode; large?: boolean }) {
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center rounded-md border border-border-strong bg-secondary font-sans font-medium text-foreground-strong",
        large ? "h-10 min-w-10 px-3 text-xl" : "h-8 min-w-8 px-2 text-body",
      )}
    >
      {children}
    </kbd>
  );
}

/**
 * One sentence about a state the person has to know: something is degraded
 * (`warning`) or failed (`fault`). Body ink on an ordinary card; the hue is on
 * the glyph only.
 */
export function Notice({
  tone = "warning",
  children,
  action,
  testId,
}: {
  tone?: "warning" | "fault";
  children: ReactNode;
  action?: ReactNode;
  testId?: string;
}) {
  const Icon = tone === "fault" ? CircleAlert : AlertTriangle;
  return (
    <div
      role={tone === "fault" ? "alert" : "status"}
      className="flex items-center gap-stack rounded-lg border border-border bg-card px-block py-3 shadow-rim"
      data-testid={testId}
    >
      <Icon
        aria-hidden="true"
        className={cn("h-5 w-5 shrink-0", tone === "fault" ? "text-destructive" : "text-warning")}
      />
      <p className="min-w-0 flex-1 text-body text-foreground">{children}</p>
      {action}
    </div>
  );
}

/** An icon-only action. `label` is its accessible name and its tooltip. */
export const IconAction = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string; testId?: string }
>(function IconAction({ label, testId, className, children, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      data-testid={testId}
      className={cn(
        "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-foreground-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-strong disabled:pointer-events-none disabled:opacity-50 [&>svg]:h-[18px] [&>svg]:w-[18px]",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
});

/** The search field of a list. */
export function SearchField({
  value,
  onChange,
  label,
  testId,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Placeholder and accessible name. */
  label: string;
  testId?: string;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={label}
        aria-label={label}
        data-testid={testId}
        className="h-10 w-full rounded-md bg-input pl-9 pr-3 text-title text-foreground placeholder:text-faint-foreground focus:outline-none focus:ring-2 focus:ring-border-strong"
      />
    </div>
  );
}

/** The designed empty state: one sentence and, at most, one action. */
export function Empty({
  icon,
  children,
  action,
  testId,
}: {
  icon?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <div
      className="flex flex-col items-center gap-stack rounded-lg border border-border bg-card px-block py-12 text-center shadow-rim"
      data-testid={testId}
    >
      {icon && <span className="text-muted-foreground [&>svg]:h-6 [&>svg]:w-6">{icon}</span>}
      <p className="text-title text-foreground">{children}</p>
      {action}
    </div>
  );
}

/** A group at its real height while its rows load. */
export function LoadingGroup({ rows = 3, testId }: { rows?: number; testId?: string }) {
  return (
    <div
      aria-busy="true"
      className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card shadow-rim"
      data-testid={testId}
    >
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex min-h-14 items-center justify-between px-block">
          <SkeletonBar className="h-4 w-40" />
          <SkeletonBar className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}
