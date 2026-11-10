/**
 * The sidebar's foot: take all of the memory along (one zip with a JSON list,
 * the readable Markdown pages and the re-importable bundle), bring a bundle
 * back in, or bring memories over from another assistant.
 */
import { lazy, Suspense, useRef, useState } from "react";
import { Download, Loader2, Sparkles, Upload } from "lucide-react";
import { fill, useT } from "@/i18n";
import { exportUrl, importBundle } from "@/lib/personalMemoryApi";

// The import review is not needed until the person asks for it.
const ForeignImportSheet = lazy(() =>
  import("./ForeignImportSheet").then((module) => ({ default: module.ForeignImportSheet })),
);

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
  const [foreign, setForeign] = useState(false);

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
      <p data-testid="vault-portable-switch" className="px-2.5 pb-1 text-[11px] leading-snug text-faint-foreground">{t("vault.portable_switch")}</p>
      <a href={exportUrl("all")} download data-testid="vault-export-all" title={t("memory_trust.export_all_hint")} className={item}>
        <Download className="h-3.5 w-3.5" /> {t("memory_trust.export_all")}
      </a>
      <button type="button" className={item} disabled={busy} onClick={() => fileRef.current?.click()} data-testid="vault-import">
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />} {t("vault.import")}
      </button>
      <button type="button" className={item} onClick={() => setForeign(true)} data-testid="vault-import-foreign">
        <Sparkles className="h-3.5 w-3.5" /> {t("memory_trust.import_open")}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={(event) => void pick(event.target.files?.[0])}
      />
      {foreign && (
        <Suspense fallback={null}>
          <ForeignImportSheet
            open={foreign}
            onClose={() => setForeign(false)}
            onSaved={(message) => {
              setForeign(false);
              onDone(message);
            }}
            onError={onError}
          />
        </Suspense>
      )}
    </div>
  );
}
