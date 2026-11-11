import { PanelRight } from "lucide-react";

import type { DiffFile } from "@/components/agentchat/toolDiff";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** How much an edit added and removed: "+8 −2", nothing when it changed nothing. */
export function DiffStat({ added, removed }: { added: number; removed: number }) {
  if (!added && !removed) return null;
  return <span className="inline-flex shrink-0 items-baseline gap-1.5 text-[13px] tabular-nums">
    {added > 0 && <span className="text-success">+{added}</span>}
    {removed > 0 && <span className="text-destructive">−{removed}</span>}
  </span>;
}

/**
 * What one call changed, file by file: the path, then the lines it added and
 * removed. With `onOpen`, the path is a button that shows the file in the
 * side panel.
 */
export function DiffView({ files, onOpen, className }: {
  files: DiffFile[];
  onOpen?: (file: DiffFile) => void;
  className?: string;
}) {
  const t = useT();
  return <div className={cn("space-y-2", className)}>
    {files.map((file, index) => <div key={`${file.path}:${index}`} className="overflow-hidden rounded-lg border border-border bg-card">
      {file.path && <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 font-mono text-xs text-muted-foreground">
        {onOpen
          ? <button type="button" onClick={() => onOpen(file)} title={t("thread_turn.open_beside")} data-testid="thread-diff-open"
            className="group/open flex min-w-0 flex-1 items-center gap-1.5 rounded-sm text-left hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="min-w-0 truncate underline decoration-muted-foreground/40 underline-offset-[3px] group-hover/open:decoration-foreground/60">{file.path}</span>
            <PanelRight aria-hidden className="h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover/open:opacity-100 group-focus-visible/open:opacity-100" />
          </button>
          : <span className="min-w-0 flex-1 truncate">{file.path}</span>}
        <DiffStat added={file.added} removed={file.removed} />
      </div>}
      <pre className="m-0 max-h-80 overflow-auto py-1 font-mono text-xs leading-5 scrollbar-jarvis">
        {file.lines.map((line, i) => line.kind === "gap"
          ? <div key={i} className="px-3 text-muted-foreground">⋯</div>
          : <div key={i} className={cn("whitespace-pre px-3", line.kind === "add" && "diff-line-add", line.kind === "del" && "diff-line-del")}>
            <span aria-hidden className="mr-2 select-none opacity-60">{line.kind === "add" ? "+" : line.kind === "del" ? "-" : " "}</span>{line.text}
          </div>)}
        {file.truncated > 0 && <div className="px-3 text-muted-foreground">… {file.truncated} more lines</div>}
      </pre>
    </div>)}
  </div>;
}
