/**
 * Copying a thread message, as a button under it and as right-click entries
 * on it (see lib/contextActions.ts).
 */
import { useState } from "react";
import { Check, Copy, Volume2 } from "lucide-react";

import { useT } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import { toggleReadAloud } from "@/lib/readAloud";
import { useContextActions } from "@/hooks/useContextActions";

/** For a right-click entry: a refused clipboard surfaces as the menu's error toast. */
async function copyOrThrow(text: string): Promise<void> {
  if (!(await robustCopy(text))) throw new Error("clipboard refused the text");
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return <button type="button" aria-label={label} title={label}
    onClick={() => { void robustCopy(text).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1200); }); }}
    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
  </button>;
}

/** Right-click on a sent message: Copy message. */
export function useMessageMenu(text: string) {
  const t = useT();
  return useContextActions(text ? () => [
    { id: "copy-message", label: t("ide_threads.copy_message"), icon: Copy, run: () => copyOrThrow(text) },
  ] : null);
}

/** Right-click on a finished answer: Copy answer, Read aloud. */
export function useAnswerMenu(turnId: string, answer: string, running: boolean) {
  const t = useT();
  return useContextActions(answer && !running ? () => [
    { id: "copy-answer", label: t("thread_turn.copy_answer"), icon: Copy, run: () => copyOrThrow(answer) },
    { id: "read-aloud", label: t("thread_turn.read_aloud"), icon: Volume2, run: () => toggleReadAloud(turnId, answer) },
  ] : null);
}
