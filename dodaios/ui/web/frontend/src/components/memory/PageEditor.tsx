/**
 * Plain Markdown editing for one page, with `[[` link completion.
 *
 * The file on disk stays the source of truth: the editor saves the body only
 * (frontmatter is kept by the server), refuses to overwrite a page that
 * changed since it was opened, and Ctrl/Cmd+S saves while Escape cancels.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Eye, Loader2, PencilLine } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { MemoryPageSummary } from "@/lib/memoryApi";
import { KindIcon } from "./KindIcon";

interface Suggestion {
  start: number;
  query: string;
}

export function PageEditor({
  initialBody,
  pages,
  onSave,
  onCancel,
  renderPreview,
}: {
  initialBody: string;
  pages: MemoryPageSummary[];
  onSave: (body: string) => Promise<void>;
  onCancel: () => void;
  renderPreview: (body: string) => JSX.Element;
}) {
  const t = useT();
  const [body, setBody] = useState(initialBody);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [highlight, setHighlight] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const dirty = body !== initialBody;

  const slugCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const page of pages) counts.set(page.slug.toLowerCase(), (counts.get(page.slug.toLowerCase()) ?? 0) + 1);
    return counts;
  }, [pages]);

  const matches = useMemo(() => {
    if (!suggestion) return [];
    const needle = suggestion.query.toLowerCase();
    return pages
      .filter((page) => page.group !== "system" && !page.empty)
      .filter((page) => !needle || page.title.toLowerCase().includes(needle) || page.slug.includes(needle))
      .sort((a, b) => Number(b.group === "knowledge") - Number(a.group === "knowledge") || b.links_in - a.links_in)
      .slice(0, 7);
  }, [pages, suggestion]);

  useEffect(() => setHighlight(0), [suggestion?.query]);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const readSuggestion = (value: string, caret: number) => {
    const before = value.slice(0, caret);
    const open = before.lastIndexOf("[[");
    if (open < 0 || before.slice(open).includes("]]") || before.slice(open).includes("\n")) {
      setSuggestion(null);
      return;
    }
    setSuggestion({ start: open, query: before.slice(open + 2) });
  };

  const insert = (page: MemoryPageSummary) => {
    const el = area.current;
    if (!el || !suggestion) return;
    const unique = (slugCounts.get(page.slug.toLowerCase()) ?? 0) === 1;
    const target = unique ? page.slug : page.path.replace(/\.md$/i, "");
    const label = unique && page.title.toLowerCase() !== page.slug.toLowerCase() ? `|${page.title}` : "";
    const caret = el.selectionStart;
    const after = body.slice(caret).startsWith("]]") ? body.slice(caret + 2) : body.slice(caret);
    const link = `[[${target}${label}]]`;
    const next = body.slice(0, suggestion.start) + link + after;
    setBody(next);
    setSuggestion(null);
    requestAnimationFrame(() => {
      el.focus();
      const position = suggestion.start + link.length;
      el.setSelectionRange(position, position);
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      void save();
      return;
    }
    if (suggestion && matches.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlight((value) => (value + 1) % matches.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlight((value) => (value - 1 + matches.length) % matches.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        insert(matches[highlight]);
        return;
      }
    }
    if (event.key === "Escape") {
      event.preventDefault();
      if (suggestion) setSuggestion(null);
      else onCancel();
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="memory-editor">
      <div className="flex items-center gap-1 rounded-lg border border-border bg-sidebar p-1">
        <ModeButton active={!preview} onClick={() => setPreview(false)} icon={<PencilLine aria-hidden />} label={t("memory_view.write")} />
        <ModeButton active={preview} onClick={() => setPreview(true)} icon={<Eye aria-hidden />} label={t("memory_view.preview")} />
        <span className="ml-auto hidden pr-2 text-xs text-foreground-faint sm:inline">{t("memory_view.editor_hint")}</span>
      </div>

      {preview ? (
        <div className="min-h-[320px] rounded-lg border border-border px-6 py-5">{renderPreview(body)}</div>
      ) : (
        <div className="relative">
          <textarea
            ref={area}
            autoFocus
            value={body}
            data-escape-local=""
            spellCheck
            onChange={(event) => {
              setBody(event.target.value);
              readSuggestion(event.target.value, event.target.selectionStart);
            }}
            onKeyDown={onKeyDown}
            onClick={(event) => readSuggestion(body, event.currentTarget.selectionStart)}
            onBlur={() => window.setTimeout(() => setSuggestion(null), 150)}
            aria-label={t("memory_view.editor_label")}
            className="block min-h-[420px] w-full resize-y rounded-lg border border-border bg-background px-5 py-4 font-mono text-sm leading-6 text-foreground outline-none focus:border-border-strong"
          />
          {suggestion && matches.length > 0 && (
            <ul
              role="listbox"
              aria-label={t("memory_view.link_suggestions")}
              className="absolute left-0 right-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-float"
            >
              {matches.map((page, index) => (
                <li key={page.path} role="option" aria-selected={index === highlight}>
                  <button
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      insert(page);
                    }}
                    className={cn(
                      "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm",
                      index === highlight ? "bg-secondary text-foreground-strong" : "text-foreground hover:bg-secondary",
                    )}
                  >
                    <KindIcon kind={page.kind} className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{page.title}</span>
                    <span className="truncate font-mono text-xs text-foreground-faint">{page.folder}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          {t("memory_view.cancel")}
        </Button>
        <Button size="sm" onClick={() => void save()} disabled={busy || !dirty} data-testid="memory-editor-save">
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {t("memory_view.save")}
        </Button>
      </div>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: JSX.Element;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors [&>svg]:h-3.5 [&>svg]:w-3.5",
        active ? "bg-background text-foreground-strong shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
