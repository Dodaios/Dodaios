/**
 * The two shapes every list on "Built for you" is made of: a section (a small
 * label over one bordered group) and a row (an icon tile, a title, one quiet
 * line under it, and whatever belongs on the right). One shape for
 * suggestions, helpers and repeats keeps the page reading as one list.
 */
import type { KeyboardEvent, ReactNode, Ref } from "react";
import { cn } from "@/lib/utils";

export function Section({
  id,
  title,
  count,
  aside,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section data-testid={`shelf-${id}`} aria-labelledby={`shelf-${id}-title`} className="mt-10">
      <div className="mb-2.5 flex items-baseline gap-2 px-1">
        <h2 id={`shelf-${id}-title`} className="text-sm font-medium text-foreground">
          {title}
        </h2>
        {count !== undefined && <span className="text-sm tabular-nums text-muted-foreground">{count}</span>}
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function Group({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">{children}</ul>;
}

export function Row({
  icon,
  title,
  sub,
  right,
  muted = false,
  selected = false,
  onClick,
  testId = "build-row",
  data,
  rowRef,
}: {
  icon: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  muted?: boolean;
  selected?: boolean;
  onClick?: () => void;
  testId?: string;
  data?: Record<string, string | undefined>;
  rowRef?: Ref<HTMLLIElement>;
}) {
  const dataAttrs = Object.fromEntries(Object.entries(data ?? {}).map(([k, v]) => [`data-${k}`, v]));
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (onClick && event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      onClick();
    }
  };
  return (
    <li ref={rowRef}>
      <div
        data-testid={testId}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
        aria-pressed={onClick ? selected : undefined}
        onKeyDown={onKey}
        data-selected={selected || undefined}
        {...dataAttrs}
        onClick={onClick}
        className={cn(
          "flex items-center gap-4 px-4 py-3.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          onClick && "cursor-pointer",
          selected ? "bg-secondary" : onClick && "hover:bg-secondary/60",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary",
            muted ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("truncate text-[15px] leading-snug", muted ? "text-muted-foreground" : "text-foreground-strong")}>
            {title}
          </p>
          {sub && <p className="mt-0.5 truncate text-sm text-muted-foreground">{sub}</p>}
        </div>
        {right && (
          <div className="flex shrink-0 items-center gap-3" onClick={(event) => event.stopPropagation()}>
            {right}
          </div>
        )}
      </div>
    </li>
  );
}
