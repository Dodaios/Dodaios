import { useEffect, useMemo, useState } from "react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { QuickTooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useCodeEditorStore } from "@/store/codeEditor";
import { useEventStore } from "@/store/events";
import { FileTypeIcon } from "../../explorer/FileTypeIcon";
import { loadPaneChanges, type PaneChanges, type ReviewFile } from "../../../paneChangesApi";
import { agoLabel } from "../gitBadges";
import { Codicon, Twistie } from "./Codicon";
import type { DiffSource } from "./DiffDialog";
import { scmApi, type ScmLetter, type ScmStatus } from "./scmApi";
import { baseName, dirName, letterTone } from "./scmModel";
import type { ScmCommands } from "./useScm";

const ROW = 22;
/** How often the session's list is read again while it is on screen. */
const POLL_MS = 8_000;

const LETTER: Record<string, ScmLetter> = { added: "A", untracked: "U", deleted: "D", conflicted: "!", modified: "M" };

/** The one agent session the Changes view is narrowed to. */
export interface SessionPick {
  pane: string;
  /** "Claude Code", "Codex", … as the pane shows it. */
  agentName: string;
  /** The pane's title, when it has one. */
  title: string;
}

/**
 * Every file one agent session wrote, committed or not, compared with the code
 * before its first change. The files come from the agent's own record of its
 * edits (and the commits its shell made), so other panes' work in the same
 * folder stays out.
 */
export function SessionChanges({
  workspaceId,
  session,
  status,
  commands,
  revision,
  onDiff,
  onClear,
}: {
  workspaceId: string;
  session: SessionPick;
  status: ScmStatus;
  commands: ScmCommands;
  /** Bumped when the repository changed: the list reads again. */
  revision: string;
  onDiff: (source: DiffSource) => void;
  onClear: () => void;
}) {
  const t = useT();
  const lang = useRunLocale();
  const pushToast = useEventStore((state) => state.pushToast);
  const [changes, setChanges] = useState<PaneChanges | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(true);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let alive = true;
    loadPaneChanges({ workspaceId, pane: session.pane }, "pane", round > 0)
      .then((answer) => {
        if (!alive) return;
        setChanges(answer);
        setError("");
      })
      .catch((err: Error) => alive && setError(err.message));
    const timer = window.setTimeout(() => setRound((value) => value + 1), POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [workspaceId, session.pane, revision, round]);

  useEffect(() => {
    setChanges(null);
    setError("");
  }, [workspaceId, session.pane]);

  // Pending files can be staged or discarded like any other; their repository path carries the prefix.
  const pending = useMemo(() => new Set(status.changes.map((file) => file.path)), [status.changes]);
  const files = (changes?.files ?? []).filter((file) => !file.is_directory);
  const repoPath = (file: ReviewFile) => `${changes?.ownCheckout ? "" : status.prefix}${file.path}`;
  const actionable = (file: ReviewFile) => !changes?.ownCheckout && pending.has(repoPath(file));

  const openDiff = (file: ReviewFile) => {
    if (!changes?.base) {
      // No base: an older reading of uncommitted files only. The editor's diff shows those.
      if (changes?.ownCheckout) return pushToast("info", t("ide_side_panel.git.scm.outside_workspace"));
      useCodeEditorStore.getState().openFile(workspaceId, file.path, { mode: "diff" });
      return;
    }
    const base = changes.base;
    // A file in the shared folder opens in the editor's diff, like any other
    // change, compared with the code before the session's first edit. A pane's
    // own worktree and a deleted file have nothing the editor could open.
    if (!changes.ownCheckout && file.status !== "deleted") {
      useCodeEditorStore.getState().openFile(workspaceId, file.path, {
        mode: "diff",
        base: { ref: base, label: fill(t("ide_side_panel.git.scm.session_diff_badge"), { pane: session.pane }) },
      });
      return;
    }
    onDiff({
      title: `${baseName(file.path)} (${session.pane})`,
      path: file.path,
      load: () => scmApi.sessionFile(workspaceId, session.pane, file.path, base),
    });
  };

  const since = changes?.sinceMs ? fill(t("ide_side_panel.git.scm.session_since"), { when: agoLabel(changes.sinceMs / 1000, lang, t) }) : "";
  const stageable = files.filter(actionable).map(repoPath);

  return (
    <div data-testid="scm-session">
      <div data-testid="scm-session-row" className="flex h-[22px] items-center pl-[8px] pr-[8px]" style={{ background: "var(--scm-hover)" }}>
        <Codicon name="filter-filled" className="mr-[6px]" />
        <QuickTooltip content={session.title || session.pane} side="bottom" className="flex min-w-0 flex-1 items-baseline overflow-hidden whitespace-nowrap">
          <span className="truncate">
            {session.agentName ? `${session.pane} · ${session.agentName}` : session.pane}
          </span>
          {since && <span className="ml-[0.5em] min-w-0 truncate text-[0.9em] opacity-70">{since}</span>}
        </QuickTooltip>
        <QuickTooltip content={t("ide_side_panel.git.scm.session_clear")} side="bottom" className="inline-flex shrink-0">
          <button type="button" data-testid="scm-session-clear" aria-label={t("ide_side_panel.git.scm.session_clear")} onClick={onClear} className="scm-action">
            <Codicon name="close" />
          </button>
        </QuickTooltip>
      </div>
      <div
        role="treeitem"
        aria-expanded={open}
        data-testid="scm-group-session"
        onClick={() => setOpen((value) => !value)}
        style={{ height: ROW, paddingLeft: 8 }}
        className="scm-row flex cursor-pointer select-none items-center pr-[12px]"
      >
        <Twistie open={open} />
        <span className="min-w-0 flex-1 truncate">{t("ide_side_panel.git.scm.session_group")}</span>
        {stageable.length > 0 && (
          <span className="scm-actions shrink-0 items-center gap-[2px] pr-1">
            <QuickTooltip content={t("ide_side_panel.git.scm.stage_session")} side="bottom" className="inline-flex shrink-0">
              <button
                type="button"
                data-testid="scm-session-stage-all"
                aria-label={t("ide_side_panel.git.scm.stage_session")}
                onClick={(event) => {
                  event.stopPropagation();
                  void commands.stage(stageable);
                }}
                className="scm-action"
              >
                <Codicon name="add" />
              </button>
            </QuickTooltip>
          </span>
        )}
        <span data-testid="scm-session-count" className="scm-badge ml-1 shrink-0 tabular-nums">
          {files.length}
        </span>
      </div>
      {open && (
        <>
          {!changes && !error && (
            <div className="flex h-[22px] items-center" style={{ paddingLeft: 38 }}>
              <Codicon name="loading" spin />
            </div>
          )}
          {error && (
            <p className="px-[20px] py-[4px] text-[13px]" style={{ color: "var(--scm-deleted)" }}>
              {error}
            </p>
          )}
          {changes && !changes.available && <p className="px-[20px] py-[4px] text-[13px] opacity-70">{changes.reason}</p>}
          {changes?.available && files.length === 0 && (
            <p data-testid="scm-session-empty" className="px-[20px] py-[4px] text-[13px] leading-[18px] opacity-70">
              {t("ide_side_panel.git.scm.session_empty")}
            </p>
          )}
          {files.map((file) => {
            const letter = LETTER[file.status] ?? "M";
            const tone = letterTone(letter);
            const description = [dirName(file.path), file.committed ? t("ide_side_panel.git.scm.session_committed") : ""].filter(Boolean).join(" · ");
            return (
              <div
                key={file.path}
                role="treeitem"
                data-testid="scm-session-file"
                data-path={file.path}
                data-letter={letter}
                onClick={() => openDiff(file)}
                style={{ height: ROW, paddingLeft: 16 }}
                className="scm-row flex cursor-pointer select-none items-center"
              >
                <Twistie visible={false} />
                <FileTypeIcon path={file.path} className="mr-[6px] h-4 w-4" />
                <span className="flex min-w-0 flex-1 items-baseline overflow-hidden whitespace-nowrap">
                  <span className={cn("truncate", tone, letter === "D" && "line-through")}>{baseName(file.path)}</span>
                  {description && <span className="ml-[0.5em] min-w-0 truncate text-[0.9em] opacity-70">{description}</span>}
                </span>
                <span className="scm-actions shrink-0 items-center gap-[2px] pl-1">
                  {letter !== "D" && !changes?.ownCheckout && (
                    <button
                      type="button"
                      aria-label={t("ide_side_panel.git.scm.open_file")}
                      data-testid="scm-session-open"
                      onClick={(event) => {
                        event.stopPropagation();
                        useCodeEditorStore.getState().openFile(workspaceId, file.path, { preview: false });
                      }}
                      className="scm-action"
                    >
                      <Codicon name="go-to-file" />
                    </button>
                  )}
                  {actionable(file) && (
                    <>
                      <button
                        type="button"
                        aria-label={t("ide_side_panel.git.scm.discard_changes")}
                        data-testid="scm-session-discard"
                        onClick={(event) => {
                          event.stopPropagation();
                          void commands.discardFiles([{ path: repoPath(file), letter: letter === "A" ? "U" : letter }]);
                        }}
                        className="scm-action"
                      >
                        <Codicon name="discard" />
                      </button>
                      <button
                        type="button"
                        aria-label={t("ide_side_panel.git.scm.stage_changes")}
                        data-testid="scm-session-stage"
                        onClick={(event) => {
                          event.stopPropagation();
                          void commands.stage([repoPath(file)]);
                        }}
                        className="scm-action"
                      >
                        <Codicon name="add" />
                      </button>
                    </>
                  )}
                </span>
                {file.committed && (
                  <QuickTooltip content={t("ide_side_panel.git.scm.session_committed")} side="bottom" className="inline-flex shrink-0">
                    <Codicon name="git-commit" className="ml-[4px] opacity-70" />
                  </QuickTooltip>
                )}
                <span data-testid="scm-letter" className={cn("ml-[5px] mr-[12px] w-4 shrink-0 text-center text-[12px] font-semibold opacity-90", tone)}>
                  {letter}
                </span>
              </div>
            );
          })}
          {changes && changes.generated > 0 && (
            <p className="py-[2px] text-[12px] leading-[18px] opacity-70" style={{ paddingLeft: 38 }}>
              {fill(t("ide_side_panel.git.scm.session_generated"), { n: changes.generated })}
            </p>
          )}
        </>
      )}
    </div>
  );
}
