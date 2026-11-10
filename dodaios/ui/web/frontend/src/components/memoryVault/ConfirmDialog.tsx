/**
 * Ask before something that cannot be undone (forgetting a memory), list
 * what it affects, and show the server's reason when it refuses.
 */
import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { Button } from "@/components/ui/button";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onClose,
  onConfirm,
  items,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
  items?: string[];
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setError(null);
  }, [open]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-testid="memory-confirm-dialog"
          className="fixed left-1/2 top-[18%] z-[90] w-[min(460px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Dialog.Title className="text-base font-semibold text-foreground-strong">{title}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {description}
          </Dialog.Description>
          {items && items.length > 0 && (
            <ul className="mt-4 max-h-48 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 text-xs leading-6 text-muted-foreground">
              {items.map((item) => (
                <li key={item} className="truncate">
                  {item}
                </li>
              ))}
            </ul>
          )}
          {error && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              {t("vault.cancel")}
            </Button>
            <Button type="button" size="sm" onClick={confirm} disabled={busy}>
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
