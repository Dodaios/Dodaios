/**
 * Give a node another name: one field, Enter saves, Escape leaves it alone.
 *
 * The dialog owns the field and the error line; the caller owns the request
 * (`onRename` rejects when the server refuses, and the sentence is shown
 * under the field with the dialog still open).
 */
import { useRef, useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useT } from "@/i18n";
import type { NodeCard } from "./nodeModel";

/** Longer than any title the library can show on one line. */
const MAX_TITLE_CHARS = 160;

export function RenameNodeDialog({
  card,
  onClose,
  onRename,
}: {
  /** The node to rename; null keeps the dialog closed. */
  card: NodeCard | null;
  onClose: () => void;
  onRename: (card: NodeCard, title: string) => Promise<void>;
}) {
  const t = useT();
  const content = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);

  return (
    <Dialog.Root open={card !== null} onOpenChange={(open) => !open && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          ref={content}
          data-testid="node-rename-dialog"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // The whole name selected: typing replaces it, an arrow key edits it.
            const field = content.current?.querySelector("input");
            if (!field) return;
            event.preventDefault();
            field.focus();
            field.select();
          }}
          className="fixed left-1/2 top-[22%] z-[90] w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Dialog.Title className="text-lg font-semibold text-foreground-strong">
            {t("nodes.rename.title")}
          </Dialog.Title>
          {card && (
            <RenameForm
              key={card.key}
              card={card}
              busy={busy}
              onBusy={setBusy}
              onClose={onClose}
              onRename={onRename}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Keyed by the card, so the field always starts from that node's name. */
function RenameForm({
  card,
  busy,
  onBusy,
  onClose,
  onRename,
}: {
  card: NodeCard;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onClose: () => void;
  onRename: (card: NodeCard, title: string) => Promise<void>;
}) {
  const t = useT();
  const [title, setTitle] = useState(card.title);
  const [failed, setFailed] = useState(false);

  const next = title.trim();
  const canSave = !busy && next !== "" && next !== card.title.trim();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    onBusy(true);
    setFailed(false);
    try {
      await onRename(card, next);
      onBusy(false);
      onClose();
    } catch {
      // The caller's request failed; say so here and keep what was typed.
      onBusy(false);
      setFailed(true);
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-4">
      <label htmlFor="node-rename-field" className="sr-only">
        {t("nodes.rename.label")}
      </label>
      <Input
        id="node-rename-field"
        value={title}
        maxLength={MAX_TITLE_CHARS}
        autoComplete="off"
        spellCheck={false}
        disabled={busy}
        onChange={(event) => setTitle(event.target.value)}
        data-testid="node-rename-field"
      />
      {failed && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {t("nodes.rename.failed")}
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
          {t("nodes.cancel")}
        </Button>
        <Button type="submit" disabled={!canSave} data-testid="node-rename-save">
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {t("nodes.rename.save")}
        </Button>
      </div>
    </form>
  );
}
