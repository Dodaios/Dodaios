import { useCallback, useMemo, useRef, useState } from "react";
import { fill, useT } from "@/i18n";
import {
  commitAll,
  deleteBranch,
  fetchRemotes,
  GitApiError,
  openPullRequest,
  pullBranch,
  pushBranch,
  switchBranch,
  updateBranch,
} from "@/lib/gitApi";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";
import type { BranchRow } from "./gitOverviewApi";

/** A question the tab asks before an action that cannot be taken back. */
export interface Confirmation {
  title: string;
  body: string;
  confirmLabel: string;
  /** Offered as a checkbox: also delete the branch on GitHub. */
  remoteOption?: boolean;
  run: (options: { remote: boolean }) => Promise<void>;
}

export interface GitActions {
  /** The action in flight (`pull`, `push:feature/x`, …); "" when idle. */
  busy: string;
  confirmation: Confirmation | null;
  dismiss: () => void;
  fetch: () => Promise<void>;
  pull: () => void;
  rebase: () => void;
  /** Push the current branch, or `branch` without checking it out. */
  push: (branch?: string) => void;
  /** Stage everything and commit; resolves true when the commit was made. */
  commit: (message: string) => Promise<boolean>;
  switchTo: (branch: string) => void;
  update: (branch: string) => void;
  remove: (row: BranchRow) => void;
  createPullRequest: (branch?: string) => void;
}

/**
 * Everything the Git tab can do to the repository. Each action runs once at a
 * time, says what happened in a toast, and re-reads the overview afterwards.
 * The two that cannot be undone — rewriting local commits and deleting a
 * branch — only run from a confirmation.
 */
export function useGitActions(folder: string, branch: string, refresh: () => void): GitActions {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const [busy, setBusy] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const running = useRef(false);

  /** Runs `work`; a rejection whose code is in `handled` is returned instead of shown. */
  const run = useCallback(
    async (key: string, work: () => Promise<string>, handled: string[] = []): Promise<GitApiError | null | undefined> => {
      if (running.current || !folder) return undefined;
      running.current = true;
      setBusy(key);
      try {
        const message = await work();
        if (message) pushToast("success", message);
        return null;
      } catch (err) {
        const failure = err instanceof GitApiError ? err : new GitApiError((err as Error).message, "failed");
        if (handled.includes(failure.code)) return failure;
        pushToast("error", failure.message);
        return undefined;
      } finally {
        running.current = false;
        setBusy("");
        refresh();
      }
    },
    [folder, pushToast, refresh],
  );

  return useMemo<GitActions>(() => {
    const rebase = () =>
      setConfirmation({
        title: t("ide_side_panel.git.confirm.rebase_title"),
        body: t("ide_side_panel.git.confirm.rebase_body"),
        confirmLabel: t("ide_side_panel.git.confirm.rebase_ok"),
        run: async () => {
          await run("pull", async () => {
            await pullBranch(folder, true);
            return fill(t("ide_side_panel.git.done.rebased"), { branch });
          });
        },
      });

    const removeNow = async (row: BranchRow, force: boolean, remote: boolean) => {
      const failure = await run(
        `delete:${row.name}`,
        async () => {
          await deleteBranch(folder, row.name, { force, remote, withWorktree: Boolean(row.worktree) });
          return fill(t("ide_side_panel.git.done.deleted"), { branch: row.name });
        },
        ["unmerged"],
      );
      if (failure) {
        // The backend found commits that exist nowhere else: ask again, explicitly.
        setConfirmation({
          title: fill(t("ide_side_panel.git.confirm.delete_force_title"), { branch: row.name }),
          body: t("ide_side_panel.git.confirm.delete_force_body"),
          confirmLabel: t("ide_side_panel.git.confirm.delete_force_ok"),
          run: ({ remote: alsoRemote }) => removeNow(row, true, alsoRemote || remote),
        });
      }
    };

    return {
      busy,
      confirmation,
      dismiss: () => setConfirmation(null),
      fetch: async () => {
        await run("fetch", async () => {
          await fetchRemotes(folder);
          return "";
        });
      },
      pull: () => {
        const pulled = async () => {
          await pullBranch(folder);
          return fill(t("ide_side_panel.git.done.pulled"), { branch });
        };
        void run("pull", pulled, ["diverged"]).then((failure) => {
          if (failure) rebase();
        });
      },
      rebase,
      push: (target = "") => {
        void run(`push:${target}`, async () => fill(t("ide_side_panel.git.done.pushed"), { upstream: (await pushBranch(folder, target)).upstream }));
      },
      commit: async (message) => {
        const failure = await run("commit", async () => fill(t("ide_side_panel.git.done.committed"), { commit: (await commitAll(folder, message)).commit }));
        return failure === null;
      },
      switchTo: (target) => {
        void run(`switch:${target}`, async () => {
          await switchBranch(folder, target);
          return fill(t("ide_side_panel.git.done.switched"), { branch: target });
        });
      },
      update: (target) => {
        void run(`update:${target}`, async () => {
          await updateBranch(folder, target);
          return fill(t("ide_side_panel.git.done.updated"), { branch: target });
        });
      },
      remove: (row) =>
        setConfirmation({
          title: fill(t("ide_side_panel.git.confirm.delete_title"), { branch: row.name }),
          body: row.worktree
            ? fill(t("ide_side_panel.git.confirm.delete_body_worktree"), { path: row.worktree })
            : t("ide_side_panel.git.confirm.delete_body"),
          confirmLabel: t("ide_side_panel.git.confirm.delete_ok"),
          remoteOption: row.on_github && Boolean(row.upstream) && !row.upstream_gone,
          run: ({ remote }) => removeNow(row, false, remote),
        }),
      createPullRequest: (target = "") => {
        void run(`pr:${target}`, async () => {
          const { url } = await openPullRequest(folder, { branch: target });
          if (url) void openExternalUrl(url);
          return t("ide_side_panel.git.done.pr_opened");
        });
      },
    };
  }, [branch, busy, confirmation, folder, run, t]);
}
