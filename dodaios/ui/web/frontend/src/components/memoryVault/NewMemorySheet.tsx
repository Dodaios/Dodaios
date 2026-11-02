/**
 * Add a memory: one sentence, and optionally its kind (picked as coloured
 * chips; left alone, the app picks). Enter saves, Escape closes.
 */
import { useEffect, useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, Wand2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MEMORY_KINDS, addMemory, type MemoryKind } from "@/lib/personalMemoryApi";
import { KIND_STYLE } from "./kinds";

export function NewMemorySheet({
  open,
  name,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  name: string;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<MemoryKind | "">("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setText("");
      setKind("");
    }
  }, [open]);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      const result = await addMemory(value, kind);
      await onSaved(result.action === "existing" ? t("vault.already_known") : t("vault.saved"));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-testid="vault-new-sheet"
          className="fixed left-1/2 top-[14%] z-[90] w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 rounded-2xl border border-border-strong bg-popover p-5 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-2"
        >
          <Dialog.Title className="text-[15px] font-semibold text-foreground-strong">{t("vault.add_title")}</Dialog.Title>
          <Dialog.Description className="mt-1 text-[12px] text-muted-foreground">
            {fill(t("vault.add_hint"), { name })}
          </Dialog.Description>
          <form onSubmit={submit} className="mt-4">
            <textarea
              autoFocus
              value={text}
              maxLength={2000}
              rows={3}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
              placeholder={t("vault.composer_placeholder")}
              aria-label={t("vault.composer_placeholder")}
              className="w-full resize-none rounded-xl border border-border bg-background p-3 text-[15px] leading-snug text-foreground placeholder:text-faint-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="mt-3 flex flex-wrap gap-1.5" role="radiogroup" aria-label={t("vault.kind_label")}>
              <Chip active={kind === ""} onClick={() => setKind("")} hue="220 9% 56%" icon={<Wand2 />}>
                {t("vault.kind_auto")}
              </Chip>
              {MEMORY_KINDS.filter((k) => k !== "ephemeral").map((k) => {
                const Icon = KIND_STYLE[k].icon;
                return (
                  <Chip key={k} active={kind === k} onClick={() => setKind(k)} hue={KIND_STYLE[k].hue} icon={<Icon />}>
                    {t(`vault.kind_${k}`)}
                  </Chip>
                );
              })}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
                {t("vault.cancel")}
              </Button>
              <Button type="submit" size="sm" disabled={!text.trim() || busy}>
                {busy && <Loader2 className="animate-spin" />}
                {t("vault.remember")}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Chip({
  active,
  onClick,
  hue,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  hue: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>svg]:h-3 [&>svg]:w-3",
        active ? "border-transparent" : "border-border text-muted-foreground hover:text-foreground",
      )}
      style={active ? { backgroundColor: `hsl(${hue} / 0.16)`, color: `hsl(${hue})` } : undefined}
    >
      {icon}
      {children}
    </button>
  );
}

