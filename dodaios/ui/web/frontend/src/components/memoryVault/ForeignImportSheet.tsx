/**
 * Bring memories over from another assistant: pick its export file (a list
 * of memories or a chat export, as text, Markdown or JSON), look through what
 * was found, keep or drop each line, save the kept ones
 * (`dodaios/memory/vault/foreign_import.py`). Nothing is saved before the
 * person says so.
 */
import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { FileUp, Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  readForeignExport,
  saveForeignImport,
  type ImportCandidate,
  type ImportReading,
} from "@/lib/personalMemoryApi";

/** Largest file read in the browser (the server takes up to 20 MB of text). */
const MAX_FILE_BYTES = 20 * 1024 * 1024;

type Step = { kind: "pick" } | { kind: "reading"; name: string } | { kind: "review"; name: string; reading: ImportReading };

export function ForeignImportSheet({
  open,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const [keep, setKeep] = useState<boolean[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setStep({ kind: "pick" });
      setKeep([]);
    }
  }, [open]);

  const pick = async (file: File | undefined) => {
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      onError(t("memory_trust.import_too_large"));
      return;
    }
    setStep({ kind: "reading", name: file.name });
    try {
      const reading = await readForeignExport(file.name, await file.text());
      setKeep(reading.candidates.map((row) => !row.exists));
      setStep({ kind: "review", name: file.name, reading });
    } catch (error) {
      setStep({ kind: "pick" });
      onError(error instanceof Error ? error.message : String(error));
    }
  };

  const save = async () => {
    if (step.kind !== "review" || saving) return;
    const chosen: ImportCandidate[] = step.reading.candidates.filter((_, i) => keep[i]);
    setSaving(true);
    try {
      const result = await saveForeignImport(step.name, chosen);
      onSaved(fill(t("memory_trust.import_saved"), { added: result.added, existing: result.existing }));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const busy = step.kind === "reading" || saving;
  const kept = keep.filter(Boolean).length;

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-testid="vault-foreign-import"
          className="fixed left-1/2 top-[10%] z-[90] flex max-h-[80vh] w-[min(620px,calc(100vw-2rem))] -translate-x-1/2 flex-col rounded-2xl border border-border-strong bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-2"
        >
          <Dialog.Title className="text-[15px] font-semibold text-foreground-strong">{t("memory_trust.import_title")}</Dialog.Title>
          <Dialog.Description className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
            {t("memory_trust.import_hint")}
          </Dialog.Description>

          {step.kind !== "review" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              data-testid="vault-foreign-pick"
              className="mt-4 flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border-strong px-4 py-8 text-center text-[13px] text-muted-foreground hover:bg-sheen/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {step.kind === "reading" ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileUp className="h-5 w-5" />}
              {step.kind === "reading" ? fill(t("memory_trust.import_reading"), { file: step.name }) : t("memory_trust.import_pick")}
              <span className="text-[11px] text-faint-foreground">{t("memory_trust.import_formats")}</span>
            </button>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.markdown,.json,text/plain,text/markdown,application/json"
            className="hidden"
            data-testid="vault-foreign-file"
            onChange={(event) => void pick(event.target.files?.[0])}
          />

          {step.kind === "review" && (
            <>
              {step.reading.model_missing && (
                <p role="status" className="mt-3 rounded-lg bg-sheen/[0.05] p-2.5 text-[12px] text-foreground-secondary">
                  {t("memory_trust.import_model_missing")}
                </p>
              )}
              {step.reading.candidates.length === 0 ? (
                <p data-testid="vault-foreign-empty" className="mt-4 text-[13px] text-muted-foreground">
                  {t("memory_trust.import_nothing")}
                </p>
              ) : (
                <>
                  <div className="mt-3 flex items-center justify-between text-[12px] text-muted-foreground">
                    <span>{fill(t("memory_trust.import_found"), { count: step.reading.candidates.length, kept })}</span>
                    <span className="flex gap-2">
                      <button type="button" className="hover:text-foreground hover:underline" onClick={() => setKeep(keep.map(() => true))}>
                        {t("memory_trust.import_keep_all")}
                      </button>
                      <button type="button" className="hover:text-foreground hover:underline" onClick={() => setKeep(keep.map(() => false))}>
                        {t("memory_trust.import_drop_all")}
                      </button>
                    </span>
                  </div>
                  <ul data-testid="vault-foreign-list" className="mt-2 min-h-0 flex-1 divide-y divide-border overflow-y-auto rounded-xl border border-border">
                    {step.reading.candidates.map((row, i) => (
                      <li key={`${i}-${row.text}`}>
                        <label className={cn("flex cursor-pointer items-start gap-3 px-3 py-2 text-[13px] hover:bg-sheen/[0.03]", !keep[i] && "text-muted-foreground")}>
                          <input
                            type="checkbox"
                            checked={Boolean(keep[i])}
                            onChange={(event) => setKeep(keep.map((value, j) => (j === i ? event.target.checked : value)))}
                            data-testid="vault-foreign-row"
                            className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--accent))]"
                          />
                          <span className={cn("min-w-0 flex-1 leading-snug", !keep[i] && "line-through")}>{row.text}</span>
                          {row.exists && <span className="shrink-0 text-[11px] text-faint-foreground">{t("memory_trust.import_known")}</span>}
                        </label>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}

          <div className="mt-5 flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              {t("memory_trust.cancel")}
            </Button>
            {step.kind === "review" && (
              <Button type="button" size="sm" disabled={!kept || saving} onClick={() => void save()} data-testid="vault-foreign-save">
                {saving && <Loader2 className="animate-spin" />}
                {fill(t("memory_trust.import_save"), { count: kept })}
              </Button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
