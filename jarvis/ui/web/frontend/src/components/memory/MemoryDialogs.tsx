/**
 * The Memory section's three small dialogs: create a page, rename one, and
 * confirm an archive. They share one frame so they look and behave alike.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { KindIcon } from "./KindIcon";

function Frame({
  open,
  onClose,
  busy,
  title,
  description,
  children,
  testId,
}: {
  open: boolean;
  onClose: () => void;
  busy: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  testId: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-testid={testId}
          className="fixed left-1/2 top-[18%] z-[90] w-[min(460px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <Dialog.Title className="text-base font-semibold text-foreground-strong">{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {description}
            </Dialog.Description>
          ) : (
            <Dialog.Description className="sr-only">{title}</Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-3 text-sm text-destructive">
      {error}
    </p>
  );
}

export type CreatableKind = "entity" | "project" | "concept";
const KINDS: CreatableKind[] = ["entity", "project", "concept"];

export function NewPageDialog({
  open,
  initialTitle,
  initialKind,
  onClose,
  onCreate,
}: {
  open: boolean;
  initialTitle: string;
  initialKind: CreatableKind;
  onClose: () => void;
  onCreate: (kind: CreatableKind, title: string) => Promise<void>;
}) {
  const t = useT();
  const [title, setTitle] = useState(initialTitle);
  const [kind, setKind] = useState<CreatableKind>(initialKind);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTitle(initialTitle);
      setKind(initialKind);
      setError(null);
    }
  }, [open, initialKind, initialTitle]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate(kind, title.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame
      open={open}
      onClose={onClose}
      busy={busy}
      title={t("memory_view.new_title")}
      description={t("memory_view.new_description")}
      testId="memory-new-dialog"
    >
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">{t("memory_view.new_name")}</span>
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t("memory_view.new_name_placeholder")}
            data-escape-local=""
            className="h-9 rounded-lg border border-border bg-background px-3 text-base text-foreground outline-none placeholder:text-foreground-faint focus:border-border-strong"
          />
        </label>
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1.5 text-sm font-medium text-foreground">{t("memory_view.new_kind")}</legend>
          <div className="grid grid-cols-3 gap-2">
            {KINDS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setKind(option)}
                aria-pressed={kind === option}
                className={cn(
                  "flex h-9 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  kind === option
                    ? "border-border-strong bg-secondary text-foreground-strong"
                    : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground",
                )}
              >
                <KindIcon kind={option} className="h-3.5 w-3.5" />
                {t(`memory_view.kind_${option}`)}
              </button>
            ))}
          </div>
        </fieldset>
        <ErrorLine error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            {t("memory_view.cancel")}
          </Button>
          <Button type="submit" size="sm" disabled={busy || !title.trim()}>
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            {t("memory_view.create")}
          </Button>
        </div>
      </form>
    </Frame>
  );
}

export function RenameDialog({
  open,
  currentTitle,
  onClose,
  onRename,
}: {
  open: boolean;
  currentTitle: string;
  onClose: () => void;
  onRename: (title: string) => Promise<void>;
}) {
  const t = useT();
  const [title, setTitle] = useState(currentTitle);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setTitle(currentTitle);
      setError(null);
    }
  }, [open, currentTitle]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onRename(title.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame
      open={open}
      onClose={onClose}
      busy={busy}
      title={t("memory_view.rename_title")}
      description={t("memory_view.rename_description")}
      testId="memory-rename-dialog"
    >
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <input
          autoFocus
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          aria-label={t("memory_view.new_name")}
          data-escape-local=""
          className="h-9 rounded-lg border border-border bg-background px-3 text-base text-foreground outline-none focus:border-border-strong"
        />
        <ErrorLine error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            {t("memory_view.cancel")}
          </Button>
          <Button type="submit" size="sm" disabled={busy || !title.trim() || title.trim() === currentTitle}>
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            {t("memory_view.rename")}
          </Button>
        </div>
      </form>
    </Frame>
  );
}

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
    <Frame open={open} onClose={onClose} busy={busy} title={title} description={description} testId="memory-confirm-dialog">
      {items && items.length > 0 && (
        <ul className="mt-4 max-h-48 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs leading-6 text-muted-foreground">
          {items.slice(0, 200).map((item) => (
            <li key={item} className="truncate">
              {item}
            </li>
          ))}
          {items.length > 200 && <li>{fill(t("memory_view.and_more"), { count: items.length - 200 })}</li>}
        </ul>
      )}
      <ErrorLine error={error} />
      <div className="mt-5 flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
          {t("memory_view.cancel")}
        </Button>
        <Button type="button" size="sm" onClick={confirm} disabled={busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {confirmLabel}
        </Button>
      </div>
    </Frame>
  );
}
