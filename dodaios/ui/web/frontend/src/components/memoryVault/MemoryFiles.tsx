/**
 * The memory as files: the Markdown an export writes, one document per kind
 * plus the MEMORY.md index. Click (or Space) opens a large preview; arrow
 * keys move between files while it is open, Escape closes it.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronLeft, ChevronRight, Download, FileText, Loader2, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { exportUrl, useVaultFiles, type VaultFile } from "@/lib/personalMemoryApi";
import { KIND_STYLE } from "./kinds";

function hueOf(file: VaultFile): string {
  return file.kind === "index" ? "220 9% 56%" : KIND_STYLE[file.kind].hue;
}

function size(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

/** Frontmatter and the id comments are for re-import, not for reading. */
function readable(content: string): string {
  const body = content.replace(/^---[\s\S]*?\n---\n/, "");
  // Cut each line at its id comment; the preview renders no HTML at all either.
  return body
    .split("\n")
    .map((line) => {
      const at = line.indexOf("<!--");
      return at >= 0 ? line.slice(0, at).trimEnd() : line;
    })
    .join("\n");
}

export function MemoryFiles() {
  const t = useT();
  const query = useVaultFiles();
  const files = useMemo(() => query.data?.files ?? [], [query.data]);
  const [open, setOpen] = useState<number | null>(null);
  const [focus, setFocus] = useState(0);

  const step = useCallback(
    (delta: number) => setOpen((index) => (index === null ? index : (index + delta + files.length) % files.length)),
    [files.length],
  );

  useEffect(() => {
    if (open === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" || event.key === " ") {
        event.preventDefault();
        setOpen(null);
      } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        step(1);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        step(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, step]);

  if (query.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const current = open === null ? null : files[open];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-5 py-2.5 text-[12px] text-muted-foreground">
        <FileText className="h-3.5 w-3.5" />
        <span className="truncate">{t("vault.files_hint")}</span>
        <a
          href={exportUrl("markdown")}
          download
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 font-medium text-accent hover:bg-accent/10"
        >
          <Download className="h-3.5 w-3.5" /> {t("vault.export_markdown")}
        </a>
      </div>
      <div
        role="grid"
        tabIndex={0}
        aria-label={t("vault.mode_files")}
        data-testid="vault-files"
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            setOpen(focus);
          } else if (event.key === "ArrowRight") setFocus((i) => Math.min(files.length - 1, i + 1));
          else if (event.key === "ArrowLeft") setFocus((i) => Math.max(0, i - 1));
        }}
        className="grid min-h-0 flex-1 auto-rows-min grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-2 overflow-y-auto p-6 focus-visible:outline-none"
      >
        {files.map((file, index) => (
          <button
            key={file.name}
            type="button"
            role="gridcell"
            data-testid="vault-file"
            onClick={() => {
              setFocus(index);
              setOpen(index);
            }}
            className={cn(
              "group flex flex-col items-center gap-2 rounded-xl p-3 text-center transition-colors focus-visible:outline-none",
              focus === index ? "bg-accent-soft" : "hover:bg-sheen/[0.04]",
            )}
          >
            <Document hue={hueOf(file)} label={file.kind === "index" ? "INDEX" : "MD"} />
            <span className="w-full truncate text-[12px] font-medium text-foreground">{file.name}</span>
            <span className="-mt-1.5 text-[11px] text-muted-foreground">
              {fill(t("vault.file_meta"), { size: size(file.bytes), lines: file.lines })}
            </span>
          </button>
        ))}
      </div>

      {current && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-scrim/45 p-6 backdrop-blur-sm motion-safe:animate-in motion-safe:fade-in-0"
          onClick={() => setOpen(null)}
        >
          <div
            role="dialog"
            aria-label={current.name}
            data-testid="vault-quicklook"
            onClick={(event) => event.stopPropagation()}
            className="flex max-h-[86vh] w-[min(760px,100%)] flex-col overflow-hidden rounded-2xl border border-border-strong bg-popover shadow-float motion-safe:animate-in motion-safe:zoom-in-95"
          >
            <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
              <button
                type="button"
                aria-label={t("vault.close")}
                onClick={() => setOpen(null)}
                className="flex h-6 w-6 items-center justify-center rounded-full text-muted-foreground hover:bg-sheen/[0.08] hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: `hsl(${hueOf(current)})` }} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground-strong">{current.name}</span>
              <button
                type="button"
                aria-label={t("vault.previous")}
                onClick={() => step(-1)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sheen/[0.08]"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label={t("vault.next")}
                onClick={() => step(1)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sheen/[0.08]"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            <article className="vault-markdown min-h-0 overflow-y-auto px-8 py-6 text-[14px] leading-relaxed text-foreground [&_a]:text-accent [&_em]:text-muted-foreground [&_h1]:mb-4 [&_h1]:text-[22px] [&_h1]:font-semibold [&_h1]:text-foreground-strong [&_li]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5">
              <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{readable(current.content)}</ReactMarkdown>
            </article>
          </div>
        </div>
      )}
    </div>
  );
}

/** A page with a folded corner and a coloured band: one file at a glance. */
function Document({ hue, label }: { hue: string; label: string }) {
  return (
    <svg viewBox="0 0 64 80" className="h-20 w-16 drop-shadow-sm transition-transform group-hover:-translate-y-0.5" aria-hidden>
      <path d="M6 2h38l18 18v54a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4z" fill="hsl(var(--surface-raised))" stroke="hsl(var(--border-strong))" />
      <path d="M44 2v14a4 4 0 0 0 4 4h14" fill="hsl(var(--secondary))" stroke="hsl(var(--border-strong))" />
      {[30, 37, 44, 51].map((y, i) => (
        <rect key={y} x="11" y={y} width={i === 3 ? 26 : 42} height="2.5" rx="1.25" fill="hsl(var(--muted-foreground) / 0.35)" />
      ))}
      <path d="M2 60h60v14a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z" fill={`hsl(${hue})`} />
      <text x="32" y="73" textAnchor="middle" fontSize="9" fontWeight="700" fill="white" fontFamily="Inter, system-ui, sans-serif">
        {label}
      </text>
    </svg>
  );
}
