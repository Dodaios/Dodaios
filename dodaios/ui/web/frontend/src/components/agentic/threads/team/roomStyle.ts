import { cn } from "@/lib/utils";

/** Reading text in the team room's side column: the thread's prose, a size smaller. */
export const PROSE_COMPACT = cn(
  "prose prose-neutral max-w-none text-sm leading-6 text-foreground dark:prose-invert dark:text-foreground [overflow-wrap:anywhere]",
  "[&>div>:first-child]:mt-0 [&>div>:last-child]:mb-0",
  "prose-p:my-1.5 prose-p:text-foreground prose-li:text-foreground prose-strong:text-foreground-strong",
  "prose-headings:mb-1 prose-headings:mt-3 prose-headings:text-sm prose-headings:font-semibold prose-headings:text-foreground-strong",
  "prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[12px] prose-code:font-normal prose-code:before:hidden prose-code:after:hidden",
  "prose-pre:my-2 prose-pre:rounded-md prose-pre:border prose-pre:border-border prose-pre:bg-card prose-pre:text-xs",
  "prose-li:my-0.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-ul:pl-5 prose-ol:pl-5",
);
