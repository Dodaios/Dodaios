import { useState } from "react";
import { Check, Flag, Tags } from "lucide-react";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { MAX_FLAG_NAME, THREAD_FLAG_COLOR, THREAD_FLAG_KINDS, useThreadFlagsStore, type ThreadFlagKind } from "@/store/threadFlags";
import { ThreadMenuHeading, ThreadMenuItem } from "./ThreadPopover";

/** A flag kind's name: the person's own, else the default words in the UI language. */
export function useFlagName(): (kind: ThreadFlagKind) => string {
  const t = useT();
  const names = useThreadFlagsStore((state) => state.names);
  return (kind) => names[kind] ?? t(`ide_threads.flags.default_${kind}`);
}

/** A solid flag in its kind's colour. */
function FlagIcon({ kind, className }: { kind: ThreadFlagKind; className?: string }) {
  return <Flag aria-hidden className={cn("h-3.5 w-3.5 shrink-0", THREAD_FLAG_COLOR[kind], className)} fill="currentColor" strokeWidth={1.75} />;
}

/**
 * The flag on a thread's row, if it has one. Its name shows when the pointer
 * rests on it, and stays in sight while the row's actions show.
 */
export function ThreadFlagMark({ sessionId }: { sessionId: string }) {
  const t = useT();
  const kind = useThreadFlagsStore((state) => state.flags[sessionId]);
  const nameOf = useFlagName();
  if (!kind) return null;
  const label = fill(t("ide_threads.flags.mark"), { name: nameOf(kind) });
  return <span role="img" aria-label={label} title={nameOf(kind)} data-testid={`thread-flag-${sessionId}`} data-flag={kind}
    className="flex shrink-0 items-center">
    <FlagIcon kind={kind} />
  </span>;
}

/**
 * The flag rows of a thread's menu: one per kind with its name, a check on
 * the one set (choosing it again takes the flag off), and a row that opens
 * the names to edit.
 */
export function ThreadFlagMenuItems({ sessionId, onDone, onEditNames }: {
  sessionId: string;
  /** The menu closes after a flag is set or cleared. */
  onDone: () => void;
  onEditNames: () => void;
}) {
  const t = useT();
  const current = useThreadFlagsStore((state) => state.flags[sessionId]);
  const toggleFlag = useThreadFlagsStore((state) => state.toggleFlag);
  const nameOf = useFlagName();
  return <div role="group" aria-label={t("ide_threads.flags.heading")} data-testid="thread-flag-menu">
    {THREAD_FLAG_KINDS.map((kind) => <ThreadMenuItem key={kind} icon={<FlagIcon kind={kind} />} label={nameOf(kind)}
      selected={current === kind}
      hint={current === kind ? <Check aria-label={t("ide_threads.flags.set")} className="h-3.5 w-3.5" /> : undefined}
      onSelect={() => { toggleFlag(sessionId, kind); onDone(); }} />)}
    <ThreadMenuItem icon={<Tags className="h-3.5 w-3.5" />} label={t("ide_threads.flags.name_flags")} onSelect={onEditNames} />
  </div>;
}

/**
 * The three names to edit, in place of the menu. Saved together with Save or
 * Enter; an empty field brings the default words back.
 */
export function ThreadFlagNamesEditor({ onClose }: { onClose: () => void }) {
  const t = useT();
  const names = useThreadFlagsStore((state) => state.names);
  const renameFlag = useThreadFlagsStore((state) => state.renameFlag);
  const [draft, setDraft] = useState<Record<ThreadFlagKind, string>>(() => ({
    red: names.red ?? "", orange: names.orange ?? "", blue: names.blue ?? "",
  }));
  const save = () => {
    for (const kind of THREAD_FLAG_KINDS) renameFlag(kind, draft[kind]);
    onClose();
  };
  return <form data-testid="thread-flag-names" className="p-1"
    onSubmit={(event) => { event.preventDefault(); save(); }}>
    <ThreadMenuHeading>{t("ide_threads.flags.names_title")}</ThreadMenuHeading>
    <div className="flex flex-col gap-1.5 px-2 pt-1">
      {THREAD_FLAG_KINDS.map((kind, index) => <label key={kind} className="flex items-center gap-2">
        <FlagIcon kind={kind} />
        <input autoFocus={index === 0} value={draft[kind]} maxLength={MAX_FLAG_NAME}
          data-testid={`thread-flag-name-${kind}`}
          aria-label={t(`ide_threads.flags.name_${kind}`)}
          placeholder={t(`ide_threads.flags.default_${kind}`)}
          onChange={(event) => setDraft((previous) => ({ ...previous, [kind]: event.target.value }))}
          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring" />
      </label>)}
    </div>
    <p className="px-2 pt-2 text-xs text-muted-foreground">{t("ide_threads.flags.names_body")}</p>
    <div className="mt-2 flex justify-end gap-2 px-1 pb-1">
      <button type="button" onClick={onClose} className="rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:bg-secondary">{t("common.cancel")}</button>
      <button type="submit" className="rounded-md bg-primary px-2.5 py-1 text-sm text-primary-foreground">{t("common.save")}</button>
    </div>
  </form>;
}
