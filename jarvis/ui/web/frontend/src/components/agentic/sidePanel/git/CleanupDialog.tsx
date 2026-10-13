import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, FolderGit2, Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { deleteBranch } from "@/lib/gitApi";
import { plural } from "./gitBadges";
import type { BranchRow } from "./gitOverviewApi";

interface Kept {
  name: string;
  reason: string;
}

/**
 * Removes merged branches in one go — after showing exactly which, with every
 * one of them unticked-able. Nothing is forced: a branch whose commits exist
 * nowhere else, or whose worktree holds uncommitted changes or an open
 * workspace, is kept and listed with the reason.
 */
export function CleanupDialog({ rows, folder, onClose }: { rows: BranchRow[]; folder: string; onClose: (changed: boolean) => void }) {
  const t = useT();
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set(rows.map((row) => row.name)));
  const [phase, setPhase] = useState<"ask" | "running" | "done">("ask");
  const [progress, setProgress] = useState(0);
  const [removed, setRemoved] = useState(0);
  const [kept, setKept] = useState<Kept[]>([]);
  const stop = useRef(false);
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => cancelButton.current?.focus(), []);
  // Closing the dialog mid-run stops before the next branch. Reset on mount:
  // React's development mode runs an effect's cleanup once before the real mount.
  useEffect(() => {
    stop.current = false;
    return () => {
      stop.current = true;
    };
  }, []);

  const chosen = rows.filter((row) => picked.has(row.name));
  const withWorktree = chosen.filter((row) => row.worktree).length;
  const toggle = (name: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  const start = async () => {
    setPhase("running");
    let done = 0;
    const left: Kept[] = [];
    for (const [index, row] of chosen.entries()) {
      if (stop.current) break;
      setProgress(index + 1);
      try {
        await deleteBranch(folder, row.name, { withWorktree: Boolean(row.worktree) });
        done += 1;
      } catch (err) {
        left.push({ name: row.name, reason: (err as Error).message });
      }
    }
    setRemoved(done);
    setKept(left);
    setPhase("done");
  };
  const close = () => onClose(phase !== "ask");

  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 z-[110] flex items-center justify-center bg-background/60 p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape" && phase !== "running") {
          event.stopPropagation();
          close();
        }
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="git-cleanup-title"
        data-testid="git-cleanup"
        data-phase={phase}
        className="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-float"
      >
        <h2 id="git-cleanup-title" className="text-sm font-semibold text-foreground">
          {phase === "done"
            ? plural(t, "ide_side_panel.git.cleanup.done_title", removed)
            : plural(t, "ide_side_panel.git.cleanup.title", chosen.length)}
        </h2>

        {phase === "ask" && (
          <>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
              {t("ide_side_panel.git.cleanup.body")}
              {withWorktree > 0 && ` ${plural(t, "ide_side_panel.git.cleanup.worktrees", withWorktree)}`}
            </p>
            <ul className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-md border border-border/70">
              {rows.map((row) => (
                <li key={row.name}>
                  <label className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 hover:bg-secondary/60">
                    <input
                      type="checkbox"
                      data-testid="git-cleanup-pick"
                      data-branch={row.name}
                      checked={picked.has(row.name)}
                      onChange={() => toggle(row.name)}
                      className="h-3.5 w-3.5 shrink-0 accent-[hsl(var(--accent))]"
                    />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground">{row.name}</span>
                    {row.worktree && <FolderGit2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label={t("ide_side_panel.git.worktree_badge")} />}
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}

        {phase === "running" && (
          <div className="mt-3 space-y-2">
            <p data-testid="git-cleanup-progress" className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
              {fill(t("ide_side_panel.git.cleanup.progress"), { done: progress, total: chosen.length })}
            </p>
            <div className="h-1 overflow-hidden rounded-full bg-secondary">
              <div className="h-full bg-accent transition-[width] duration-200" style={{ width: `${(progress / Math.max(1, chosen.length)) * 100}%` }} />
            </div>
          </div>
        )}

        {phase === "done" && (
          <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
            {kept.length === 0 ? (
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Check className="h-3.5 w-3.5 text-success" aria-hidden />
                {t("ide_side_panel.git.cleanup.done_all")}
              </p>
            ) : (
              <>
                <p className="text-xs text-muted-foreground">{plural(t, "ide_side_panel.git.cleanup.kept", kept.length)}</p>
                <ul className="mt-2 space-y-1.5">
                  {kept.map((entry) => (
                    <li key={entry.name} data-testid="git-cleanup-kept" className="text-[11.5px] leading-snug">
                      <span className="font-mono text-foreground">{entry.name}</span>
                      <span className="block text-muted-foreground">{entry.reason}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <div className="mt-4 flex shrink-0 justify-end gap-2">
          {phase === "ask" && (
            <>
              <button
                ref={cancelButton}
                type="button"
                data-testid="git-cleanup-cancel"
                onClick={close}
                className="h-8 rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("ide_side_panel.git.confirm.cancel")}
              </button>
              <button
                type="button"
                data-testid="git-cleanup-ok"
                disabled={chosen.length === 0}
                onClick={() => void start()}
                className="h-8 rounded-md bg-destructive px-3 text-xs font-medium text-destructive-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                {plural(t, "ide_side_panel.git.cleanup.ok", chosen.length)}
              </button>
            </>
          )}
          {phase === "done" && (
            <button
              type="button"
              data-testid="git-cleanup-close"
              onClick={close}
              className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("ide_side_panel.git.cleanup.close")}
            </button>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
