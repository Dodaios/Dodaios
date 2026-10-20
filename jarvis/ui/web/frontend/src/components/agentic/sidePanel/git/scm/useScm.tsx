import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Cloud, GitBranch, Plus, Tag } from "lucide-react";
import { fill, useT } from "@/i18n";
import { GitApiError } from "@/lib/gitApi";
import { useEventStore } from "@/store/events";
import { Codicon } from "./Codicon";
import { scmApi, type ScmRef, type ScmStatus } from "./scmApi";
import type { QuickInput, QuickPickItem } from "./QuickInput";

const POLL_MS = 5_000;
const POLL_JITTER_MS = 1_500;

/** A choice the tab asks for before something that cannot be taken back. */
export interface Choice {
  title: string;
  body?: string;
  buttons: { id: string; label: string; primary?: boolean; destructive?: boolean }[];
}

/** The open workspace's source control state, read again every few seconds while it is on screen. */
export function useScmStatus(workspaceId: string | null) {
  const [status, setStatus] = useState<ScmStatus | null>(null);
  const [error, setError] = useState<GitApiError | null>(null);
  const [round, setRound] = useState(0);
  const last = useRef("");
  useEffect(() => {
    setStatus(null);
    setError(null);
    last.current = "";
  }, [workspaceId]);
  useEffect(() => {
    if (!workspaceId) return;
    let alive = true;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    const tick = async () => {
      const visible = typeof document === "undefined" || document.visibilityState !== "hidden";
      if (visible && useEventStore.getState().activeSection === "agentic-ide") {
        controller = new AbortController();
        try {
          const next = await scmApi.status(workspaceId, controller.signal);
          const text = JSON.stringify(next);
          // An unchanged answer keeps the same object: the list does not redraw.
          if (alive && text !== last.current) {
            last.current = text;
            setStatus(next);
          }
          if (alive) setError(null);
        } catch (err) {
          if (alive && !(err instanceof DOMException && err.name === "AbortError")) {
            setError(err instanceof GitApiError ? err : new GitApiError((err as Error).message, "failed"));
          }
        }
      }
      if (alive) timer = window.setTimeout(tick, POLL_MS + Math.random() * POLL_JITTER_MS);
    };
    void tick();
    const onFocus = () => {
      window.clearTimeout(timer);
      void tick();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      alive = false;
      controller?.abort();
      window.clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [workspaceId, round]);
  const refresh = useCallback(() => setRound((value) => value + 1), []);
  return { status, error, refresh };
}

function ChoiceDialog({ choice, onDone }: { choice: Choice; onDone: (id: string | undefined) => void }) {
  const t = useT();
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => first.current?.focus(), []);
  return createPortal(
    <div
      role="presentation"
      className="scm-portal fixed inset-0 z-[115] flex items-start justify-center p-4 pt-[12vh]"
      style={{ background: "rgba(0, 0, 0, 0.3)" }}
      onPointerDown={(event) => event.target === event.currentTarget && onDone(undefined)}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onDone(undefined);
        }
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="scm-choice-title"
        data-testid="scm-choice"
        className="flex w-full max-w-[460px] flex-col rounded-[6px] px-[20px] pb-[18px] pt-[20px]"
        style={{ background: "var(--scm-menu-bg)", color: "var(--scm-menu-fg)", border: "1px solid var(--scm-menu-border)", boxShadow: "0 0 8px 2px rgba(0, 0, 0, 0.36)" }}
      >
        <div className="flex gap-[12px]">
          <Codicon name="warning" className="!text-[24px] !leading-[24px]" />
          <div className="min-w-0 flex-1">
            <h2 id="scm-choice-title" className="whitespace-pre-line break-words text-[13px] font-semibold leading-[20px]">
              {choice.title}
            </h2>
            {choice.body && <p className="mt-[6px] whitespace-pre-line break-words text-[13px] leading-[20px] opacity-90">{choice.body}</p>}
          </div>
        </div>
        <div className="mt-[20px] flex flex-wrap justify-end gap-[8px]">
          {choice.buttons.map((button, index) => (
            <button
              key={button.id}
              ref={index === 0 ? first : undefined}
              type="button"
              data-testid={`scm-choice-${button.id}`}
              onClick={() => onDone(button.id)}
              style={index === 0 ? undefined : { background: "var(--scm-input-bg)", color: "var(--scm-fg)", border: "1px solid var(--scm-input-border)" }}
              className={index === 0 ? "scm-button inline-flex h-[26px] min-w-[80px] items-center justify-center rounded-[2px] px-[12px] text-[13px]" : "inline-flex h-[26px] min-w-[80px] items-center justify-center rounded-[2px] px-[12px] text-[13px] hover:opacity-90"}
            >
              {button.label}
            </button>
          ))}
          <button
            type="button"
            data-testid="scm-choice-cancel"
            onClick={() => onDone(undefined)}
            style={{ background: "var(--scm-input-bg)", color: "var(--scm-fg)", border: "1px solid var(--scm-input-border)" }}
            className="inline-flex h-[26px] min-w-[80px] items-center justify-center rounded-[2px] px-[12px] text-[13px] hover:opacity-90"
          >
            {t("ide_side_panel.git.confirm.cancel")}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

/** `ask(choice)` resolves with the button pressed, or undefined on cancel. */
export function useChoice(): { ask: (choice: Choice) => Promise<string | undefined>; element: ReactNode } {
  const [current, setCurrent] = useState<{ choice: Choice; resolve: (id: string | undefined) => void } | null>(null);
  const ask = useCallback(
    (choice: Choice) =>
      new Promise<string | undefined>((resolve) => {
        setCurrent((previous) => {
          previous?.resolve(undefined);
          return { choice, resolve };
        });
      }),
    [],
  );
  const element = current ? (
    <ChoiceDialog
      choice={current.choice}
      onDone={(id) => {
        current.resolve(id);
        setCurrent(null);
      }}
    />
  ) : null;
  return { ask, element };
}

const storage = {
  get(key: string): string {
    try {
      return window.localStorage.getItem(key) ?? "";
    } catch {
      return ""; // storage blocked: every question is asked again
    }
  },
  set(key: string, value: string) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // storage blocked: the choice lasts for this session only
    }
  },
};
export const scmStorage = storage;

export type CommitKind = "commit" | "amend" | "push" | "sync";
export interface CommitOptions {
  kind: CommitKind;
  /** `staged` commits the index only, `all` stages everything first; omitted = decide (smart commit). */
  scope?: "staged" | "all";
  signoff?: boolean;
  noVerify?: boolean;
}

/**
 * Every git command of the Git tab: each runs once at a time behind the
 * progress bar, reports a failure in a toast and re-reads the status. Commands
 * that pick a branch, a remote or a stash ask through the quick input; those
 * that cannot be undone ask through a choice dialog first.
 */
export function useScmCommands({
  workspaceId,
  status,
  refresh,
  quick,
  ask,
  onChanged,
}: {
  workspaceId: string;
  status: ScmStatus | null;
  refresh: () => void;
  quick: QuickInput;
  ask: (choice: Choice) => Promise<string | undefined>;
  /** History or refs may have moved: the graph reads again. */
  onChanged: () => void;
}) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const [busy, setBusy] = useState("");
  // Commands run one after another, in the order they were asked for: a quick
  // second click (stage, then unstage) waits for the first instead of racing it.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const statusRef = useRef(status);
  statusRef.current = status;

  const run = useCallback(
    <T,>(label: string, action: () => Promise<T>, { history = true }: { history?: boolean } = {}): Promise<T | undefined> => {
      pending.current += 1;
      const next = queue.current.then(async () => {
        setBusy(label);
        try {
          return await action();
        } catch (err) {
          pushToast("error", (err as Error).message);
          return undefined;
        } finally {
          pending.current -= 1;
          if (pending.current === 0) setBusy("");
          refresh();
          if (history) onChanged();
        }
      });
      queue.current = next;
      return next;
    },
    [pushToast, refresh, onChanged],
  );

  const refs = useCallback(async (): Promise<ScmRef[]> => {
    try {
      return (await scmApi.refs(workspaceId)).refs;
    } catch (err) {
      pushToast("error", (err as Error).message);
      return [];
    }
  }, [workspaceId, pushToast]);

  const refItems = useCallback(
    (list: ScmRef[], kinds: ScmRef["kind"][], skip = ""): QuickPickItem<string>[] =>
      list
        .filter((ref) => kinds.includes(ref.kind) && ref.name !== skip)
        .map((ref) => ({
          label: ref.name,
          description: `${ref.commit}${ref.subject ? ` · ${ref.subject}` : ""}`,
          icon:
            ref.kind === "tag" ? (
              <Tag className="h-3.5 w-3.5" aria-hidden />
            ) : ref.kind === "remote" ? (
              <Cloud className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <GitBranch className="h-3.5 w-3.5" aria-hidden />
            ),
          group: t(`ide_side_panel.git.scm.ref_group.${ref.kind}`),
          value: ref.name,
        })),
    [t],
  );

  const branchName = useCallback(
    (prompt: string, value = "") =>
      quick.input({
        prompt,
        placeholder: t("ide_side_panel.git.scm.branch_name_placeholder"),
        value,
        validate: (text) => (/\s|\.\.|[~^:?*[\\]|^-|^\/|\/$|\.lock$|@\{/.test(text.trim()) ? t("ide_side_panel.git.scm.branch_name_invalid") : ""),
      }),
    [quick, t],
  );

  const pickRemote = useCallback(
    async (placeholder: string): Promise<string | undefined> => {
      const remotes = statusRef.current?.remotes ?? [];
      if (remotes.length === 0) {
        pushToast("warning", t("ide_side_panel.git.scm.no_remotes"));
        return undefined;
      }
      if (remotes.length === 1) return remotes[0];
      return quick.pick(
        remotes.map((name) => ({ label: name, value: name, icon: <Cloud className="h-3.5 w-3.5" aria-hidden /> })),
        placeholder,
      );
    },
    [quick, pushToast, t],
  );

  const commands = useMemo(() => {
    const id = workspaceId;
    const push = () => run("push", () => scmApi.push(id));
    const publish = async () => {
      const remote = await pickRemote(t("ide_side_panel.git.scm.pick_remote_publish"));
      if (remote) await run("publish", () => scmApi.push(id, { remote }));
    };
    const sync = async () => {
      const current = statusRef.current;
      if (current && !current.upstream) return publish();
      if (storage.get("jarvis.git.scm.confirmSync") !== "never") {
        const answer = await ask({
          title: fill(t("ide_side_panel.git.scm.sync_confirm"), { upstream: current?.upstream ?? "" }),
          buttons: [
            { id: "ok", label: t("ide_side_panel.git.scm.ok"), primary: true },
            { id: "always", label: t("ide_side_panel.git.scm.ok_dont_ask") },
          ],
        });
        if (!answer) return;
        if (answer === "always") storage.set("jarvis.git.scm.confirmSync", "never");
      }
      await run("sync", () => scmApi.sync(id));
    };

    const commit = async (message: string, options: CommitOptions): Promise<boolean> => {
      const current = statusRef.current;
      if (!current) return false;
      const amend = options.kind === "amend";
      let scope = options.scope;
      if (!scope) {
        if (current.staged.length > 0 || current.operation === "merge") scope = "staged";
        else if (current.changes.length > 0) {
          const smart = storage.get("jarvis.git.scm.smartCommit");
          if (smart !== "always") {
            const answer = await ask({
              title: t("ide_side_panel.git.scm.smart_commit_title"),
              buttons: [
                { id: "yes", label: t("ide_side_panel.git.scm.yes"), primary: true },
                { id: "always", label: t("ide_side_panel.git.scm.always") },
              ],
            });
            if (!answer) return false;
            if (answer === "always") storage.set("jarvis.git.scm.smartCommit", "always");
          }
          scope = "all";
        } else if (!amend) {
          pushToast("info", t("ide_side_panel.git.scm.nothing_to_commit"));
          return false;
        } else scope = "staged";
      }
      if (amend && !message.trim()) {
        // An amend without a new message keeps the last one.
      } else if (!message.trim()) return false;
      const made = await run("commit", () =>
        scmApi.commitChanges(id, message, {
          amend,
          all_changes: scope === "all",
          signoff: options.signoff,
          no_verify: options.noVerify,
        }),
      );
      if (!made) return false;
      if (options.kind === "push") await run("push", () => scmApi.push(id));
      if (options.kind === "sync") await run("sync", () => scmApi.sync(id));
      return true;
    };

    const discardFiles = async (files: { path: string; letter: string }[]) => {
      if (files.length === 0) return;
      const untracked = files.filter((file) => file.letter === "U");
      const name = files[0].path.split("/").pop() ?? files[0].path;
      let title: string;
      let label: string;
      if (files.length === 1 && untracked.length === 1) {
        title = fill(t("ide_side_panel.git.scm.delete_untracked_one"), { name });
        label = t("ide_side_panel.git.scm.delete_file");
      } else if (files.length === 1) {
        title = fill(t("ide_side_panel.git.scm.discard_one"), { name });
        label = t("ide_side_panel.git.scm.discard_file");
      } else {
        title = fill(t("ide_side_panel.git.scm.discard_many"), { n: files.length });
        label = fill(t("ide_side_panel.git.scm.discard_n_files"), { n: files.length });
      }
      const answer = await ask({
        title,
        body: untracked.length ? t("ide_side_panel.git.scm.untracked_to_trash") : t("ide_side_panel.git.scm.cannot_undo"),
        buttons: [{ id: "discard", label, destructive: true }],
      });
      if (answer === "discard") await run("discard", () => scmApi.discard(id, files.map((file) => file.path)), { history: false });
    };

    const discardAll = async () => {
      const current = statusRef.current;
      if (!current || current.changes.length === 0) return;
      const untracked = current.changes.filter((file) => file.letter === "U").length;
      const tracked = current.changes.length - untracked;
      const buttons: Choice["buttons"] = [];
      if (untracked > 0) buttons.push({ id: "all", label: fill(t("ide_side_panel.git.scm.discard_all_files"), { n: current.changes.length }), destructive: true });
      if (tracked > 0) buttons.push({ id: "tracked", label: fill(t("ide_side_panel.git.scm.discard_tracked_files"), { n: tracked }), destructive: untracked === 0 });
      const answer = await ask({
        title: fill(t("ide_side_panel.git.scm.discard_all_title"), { n: current.changes.length }),
        body: untracked ? fill(t("ide_side_panel.git.scm.discard_all_body"), { n: untracked }) : t("ide_side_panel.git.scm.cannot_undo"),
        buttons,
      });
      if (answer) await run("discard", () => scmApi.discardAll(id, answer === "all"), { history: false });
    };

    const checkoutTo = async (detached = false) => {
      const list = await refs();
      type Pick = { action: "create" | "create_from" | "detached" } | { ref: string };
      const items: QuickPickItem<Pick>[] = [
        ...(detached
          ? []
          : [
              { label: t("ide_side_panel.git.scm.create_branch"), icon: <Plus className="h-3.5 w-3.5" aria-hidden />, value: { action: "create" as const } },
              { label: t("ide_side_panel.git.scm.create_branch_from"), icon: <Plus className="h-3.5 w-3.5" aria-hidden />, value: { action: "create_from" as const } },
              { label: t("ide_side_panel.git.scm.checkout_detached"), icon: <GitBranch className="h-3.5 w-3.5" aria-hidden />, value: { action: "detached" as const } },
            ]),
        ...refItems(list, detached ? ["head", "remote", "tag"] : ["head", "remote", "tag"]).map((item) => ({ ...item, value: { ref: item.value } })),
      ];
      const picked = await quick.pick(items, detached ? t("ide_side_panel.git.scm.pick_detached") : t("ide_side_panel.git.scm.pick_checkout"));
      if (!picked) return;
      if ("ref" in picked) {
        await run("checkout", () => scmApi.checkout(id, picked.ref, detached));
        return;
      }
      if (picked.action === "detached") return checkoutTo(true);
      if (picked.action === "create") return createBranch();
      return createBranchFrom();
    };

    const createBranch = async (start = "") => {
      const name = await branchName(t("ide_side_panel.git.scm.branch_name_prompt"));
      if (name?.trim()) await run("branch", () => scmApi.createBranch(id, name.trim(), start));
    };
    const createBranchFrom = async () => {
      const list = await refs();
      const start = await quick.pick(refItems(list, ["head", "remote", "tag"]), t("ide_side_panel.git.scm.pick_branch_from"));
      if (start) await createBranch(start);
    };
    const renameBranch = async () => {
      const current = statusRef.current?.branch ?? "";
      const name = await branchName(t("ide_side_panel.git.scm.rename_prompt"), current);
      if (name?.trim() && name.trim() !== current) await run("rename", () => scmApi.renameBranch(id, name.trim()));
    };
    const deleteBranch = async () => {
      const list = await refs();
      const name = await quick.pick(refItems(list, ["head"], statusRef.current?.branch), t("ide_side_panel.git.scm.pick_delete_branch"));
      if (!name) return;
      let unmerged = false;
      await run("delete", async () => {
        try {
          await scmApi.deleteBranch(id, name);
        } catch (err) {
          // Its commits are on no other branch: ask before deleting them for good.
          if (!(err instanceof GitApiError && err.code === "unmerged")) throw err;
          unmerged = true;
        }
      });
      if (unmerged) await deleteBranchForce(name);
    };
    const deleteBranchForce = async (name: string) => {
      const answer = await ask({
        title: fill(t("ide_side_panel.git.scm.delete_unmerged"), { name }),
        buttons: [{ id: "force", label: t("ide_side_panel.git.scm.delete_branch_button"), destructive: true }],
      });
      if (answer) await run("delete", () => scmApi.deleteBranch(id, name, true));
    };
    const mergeBranch = async () => {
      const list = await refs();
      const ref = await quick.pick(refItems(list, ["head", "remote", "tag"], statusRef.current?.branch), t("ide_side_panel.git.scm.pick_merge"));
      if (!ref) return;
      const answer = await run("merge", () => scmApi.merge(id, ref));
      if (answer?.result === "conflict") pushToast("warning", t("ide_side_panel.git.scm.merge_conflicts"));
    };
    const rebaseBranch = async () => {
      const list = await refs();
      const ref = await quick.pick(refItems(list, ["head", "remote"], statusRef.current?.branch), t("ide_side_panel.git.scm.pick_rebase"));
      if (!ref) return;
      const answer = await run("rebase", () => scmApi.rebase(id, ref));
      if (answer?.result === "conflict") pushToast("warning", t("ide_side_panel.git.scm.rebase_conflicts"));
    };

    const pullFrom = async () => {
      const remote = await pickRemote(t("ide_side_panel.git.scm.pick_remote_pull"));
      if (!remote) return;
      const list = await refs();
      const branch = await quick.pick(
        refItems(list.filter((ref) => ref.kind === "remote" && ref.name.startsWith(`${remote}/`)), ["remote"]).map((item) => ({
          ...item,
          value: item.value.slice(remote.length + 1),
        })),
        t("ide_side_panel.git.scm.pick_branch_pull"),
      );
      if (branch) await run("pull", () => scmApi.pull(id, { remote, branch }));
    };
    const pushTo = async () => {
      const remote = await pickRemote(t("ide_side_panel.git.scm.pick_remote_push"));
      if (remote) await run("push", () => scmApi.push(id, { remote }));
    };

    const addRemote = async () => {
      const name = await quick.input({
        prompt: t("ide_side_panel.git.scm.remote_name_prompt"),
        validate: (text) => (/^[A-Za-z0-9._-]+$/.test(text.trim()) || !text ? "" : t("ide_side_panel.git.scm.remote_name_invalid")),
      });
      if (!name?.trim()) return;
      const url = await quick.input({ prompt: t("ide_side_panel.git.scm.remote_url_prompt"), placeholder: "https://github.com/owner/repo.git" });
      if (url?.trim()) await run("remote", () => scmApi.addRemote(id, name.trim(), url.trim()));
    };
    const removeRemote = async () => {
      const remotes = statusRef.current?.remotes ?? [];
      const name = await quick.pick(
        remotes.map((remote) => ({ label: remote, value: remote, icon: <Cloud className="h-3.5 w-3.5" aria-hidden /> })),
        t("ide_side_panel.git.scm.pick_remote_remove"),
      );
      if (name) await run("remote", () => scmApi.removeRemote(id, name));
    };

    const stash = async (options: { include_untracked?: boolean; staged?: boolean } = {}) => {
      const message = await quick.input({ prompt: t("ide_side_panel.git.scm.stash_message_prompt"), placeholder: t("ide_side_panel.git.scm.stash_message_placeholder") });
      if (message === undefined) return;
      await run("stash", () => scmApi.stash(id, { message, ...options }), { history: false });
    };
    const pickStash = async (placeholder: string) => {
      let stashes: { ref: string; message: string }[] = [];
      try {
        stashes = (await scmApi.stashes(id)).stashes;
      } catch (err) {
        pushToast("error", (err as Error).message);
        return undefined;
      }
      if (stashes.length === 0) {
        pushToast("info", t("ide_side_panel.git.scm.no_stashes"));
        return undefined;
      }
      return quick.pick(stashes.map((entry) => ({ label: entry.message, description: entry.ref, value: entry.ref })), placeholder);
    };
    const applyStash = async (pop: boolean, latest: boolean) => {
      const ref = latest ? "" : await pickStash(pop ? t("ide_side_panel.git.scm.pick_stash_pop") : t("ide_side_panel.git.scm.pick_stash_apply"));
      if (ref === undefined) return;
      await run("stash", () => scmApi.stashApply(id, ref, pop), { history: false });
    };
    const dropStash = async () => {
      const ref = await pickStash(t("ide_side_panel.git.scm.pick_stash_drop"));
      if (!ref) return;
      const answer = await ask({
        title: fill(t("ide_side_panel.git.scm.drop_stash_confirm"), { ref }),
        buttons: [{ id: "drop", label: t("ide_side_panel.git.scm.drop"), destructive: true }],
      });
      if (answer) await run("stash", () => scmApi.stashDrop(id, ref), { history: false });
    };
    const dropAllStashes = async () => {
      const answer = await ask({
        title: fill(t("ide_side_panel.git.scm.drop_all_confirm"), { n: statusRef.current?.stashes ?? 0 }),
        buttons: [{ id: "drop", label: t("ide_side_panel.git.scm.drop_all"), destructive: true }],
      });
      if (answer) await run("stash", () => scmApi.stashDrop(id, "", true), { history: false });
    };

    const createTag = async (ref = "") => {
      const name = await quick.input({ prompt: t("ide_side_panel.git.scm.tag_name_prompt"), placeholder: "v1.0.0" });
      if (!name?.trim()) return;
      const message = await quick.input({ prompt: t("ide_side_panel.git.scm.tag_message_prompt"), placeholder: t("ide_side_panel.git.scm.tag_message_placeholder") });
      if (message === undefined) return;
      await run("tag", () => scmApi.createTag(id, name.trim(), message, ref));
    };
    const deleteTag = async () => {
      const list = await refs();
      const name = await quick.pick(refItems(list, ["tag"]), t("ide_side_panel.git.scm.pick_tag_delete"));
      if (name) await run("tag", () => scmApi.deleteTag(id, name));
    };

    const undoLastCommit = async (): Promise<string | undefined> => {
      const answer = await run("undo", () => scmApi.undoCommit(id));
      return answer?.message;
    };

    return {
      push,
      publish,
      sync,
      commit,
      pull: (rebase = false) => run("pull", () => scmApi.pull(id, { rebase })),
      pullFrom,
      pushTo,
      pushTags: () => run("push", () => scmApi.pushTags(id)),
      fetch: (options: { prune?: boolean; all_remotes?: boolean } = {}) => run("fetch", () => scmApi.fetch(id, options)),
      stage: (paths: string[]) => run("stage", () => scmApi.stage(id, paths), { history: false }),
      stageAll: () => run("stage", () => scmApi.stageAll(id), { history: false }),
      unstage: (paths: string[]) => run("unstage", () => scmApi.unstage(id, paths), { history: false }),
      unstageAll: () => run("unstage", () => scmApi.unstageAll(id), { history: false }),
      discardFiles,
      discardAll,
      ignore: (paths: string[]) => run("ignore", () => scmApi.ignore(id, paths), { history: false }),
      checkoutTo,
      checkoutRef: (ref: string, detached = false) => run("checkout", () => scmApi.checkout(id, ref, detached)),
      createBranch,
      createBranchFrom,
      renameBranch,
      deleteBranch,
      deleteBranchForce,
      mergeBranch,
      rebaseBranch,
      addRemote,
      removeRemote,
      stash,
      applyStash,
      dropStash,
      dropAllStashes,
      createTag,
      deleteTag,
      undoLastCommit,
      operation: (action: "continue" | "abort") => run(action, () => scmApi.operation(id, action)),
      cherryPick: async (commitId: string) => {
        const answer = await run("cherry-pick", () => scmApi.cherryPick(id, commitId));
        if (answer?.result === "conflict") pushToast("warning", t("ide_side_panel.git.scm.cherry_pick_conflicts"));
      },
      revert: async (commitId: string) => {
        const answer = await run("revert", () => scmApi.revert(id, commitId));
        if (answer?.result === "conflict") pushToast("warning", t("ide_side_panel.git.scm.revert_conflicts"));
      },
    };
  }, [workspaceId, run, refs, refItems, branchName, pickRemote, quick, ask, pushToast, t]);

  return { busy, commands };
}

export type ScmCommands = ReturnType<typeof useScmCommands>["commands"];
