/**
 * The sidebar's foot: take the memory along (one zip) or bring one in.
 */
import { useRef, useState } from "react";
import { Download, Loader2, Upload } from "lucide-react";
import { fill, useT } from "@/i18n";
import { exportUrl, importBundle } from "@/lib/personalMemoryApi";

export function Portability({
  onDone,
  onError,
}: {
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const report = await importBundle(file);
      onDone(fill(t("vault.import_done"), { added: report.added, skipped: report.skipped }));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const item =
    "flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[12px] text-muted-foreground transition-colors hover:bg-sheen/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return (
    <div className="border-t border-border p-2">
      <p className="px-2.5 pb-1 pt-1 text-[11px] leading-snug text-faint-foreground">{t("vault.portable_hint")}</p>
      <a href={exportUrl("bundle")} download data-testid="vault-export-bundle" className={item}>
        <Download className="h-3.5 w-3.5" /> {t("vault.export_bundle")}
      </a>
      <button type="button" className={item} disabled={busy} onClick={() => fileRef.current?.click()} data-testid="vault-import">
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />} {t("vault.import")}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(event) => void pick(event.target.files?.[0])}
      />
    </div>
  );
}
