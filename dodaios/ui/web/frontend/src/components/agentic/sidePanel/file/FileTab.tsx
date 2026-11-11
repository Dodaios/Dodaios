import { useEffect, useState } from "react";
import { FileCode2, Loader2, RefreshCw } from "lucide-react";

import { CodeBlock } from "@/components/docs/CodeBlock";
import { Notice } from "@/components/agentic/editor/FileViewers";
import { loadTextFile, openOutsideFile } from "@/components/agentic/editor/editorApi";
import { DiffView } from "@/components/agentic/threads/ThreadDiff";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";

/** Highlighting a very long file would stall the panel; past this it reads as plain text. */
const HIGHLIGHT_MAX_CHARS = 200_000;

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: "python", pyi: "python", ts: "typescript", mts: "typescript", cts: "typescript", tsx: "tsx",
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "jsx", json: "json", jsonc: "json",
  yaml: "yaml", yml: "yaml", toml: "toml", ini: "ini", cfg: "ini", xml: "xml", svg: "xml",
  html: "html", htm: "html", css: "css", rs: "rust", go: "go", java: "java", c: "c", h: "c",
  cpp: "cpp", cc: "cpp", cxx: "cpp", hpp: "cpp", cs: "csharp", kt: "kotlin", swift: "swift",
  sql: "sql", md: "markdown", markdown: "markdown", sh: "bash", bash: "bash", zsh: "bash",
  ps1: "powershell", psm1: "powershell", diff: "diff", patch: "diff",
};

/** The highlighter's language for a file name; "" reads it as plain text. */
export function fileLanguage(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot > 0 ? LANGUAGE_BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? "" : "";
}

type Loaded =
  | { state: "loading" }
  | { state: "ready"; text: string }
  | { state: "binary" | "too_large" | "unavailable" | "no_workspace" };

/**
 * The side panel's File tab: the file a thread's work log pointed at, read
 * from disk as it is now, beside the conversation. When the click came from
 * an edit, "Change" shows what that edit did.
 *
 * The file is read through the code editor's own route. A path outside the
 * workspace is granted first, the same way a modifier-click on a terminal
 * path grants it: only this deliberate click opens a file outside the folder.
 */
export function FileTab() {
  const t = useT();
  const file = useSideFileStore((state) => state.file);
  const nonce = useSideFileStore((state) => state.nonce);
  const chatWorkspace = useIdeChatStore((state) => state.workspace?.id ?? null);
  const activeWorkspace = useIdeProjectsStore((state) => state.activeWorkspaceId);
  const workspaceId = chatWorkspace ?? activeWorkspace;
  const [view, setView] = useState<"file" | "change">("file");
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [reload, setReload] = useState(0);

  // A new click shows the file itself first.
  useEffect(() => { setView("file"); }, [nonce]);

  const absolute = file ? absoluteFilePath(file.path, file.folder) : "";
  useEffect(() => {
    if (!absolute) return;
    if (!workspaceId) { setLoaded({ state: "no_workspace" }); return; }
    let cancelled = false;
    setLoaded({ state: "loading" });
    void (async () => {
      try {
        const granted = await openOutsideFile(workspaceId, absolute);
        if (granted.kind !== "file") throw new Error("not a file");
        const text = await loadTextFile(workspaceId, granted.path);
        if (cancelled) return;
        if (text.binary) setLoaded({ state: "binary" });
        else if (text.too_large || text.text === null) setLoaded({ state: "too_large" });
        else setLoaded({ state: "ready", text: text.text });
      } catch {
        if (!cancelled) setLoaded({ state: "unavailable" });
      }
    })();
    return () => { cancelled = true; };
  }, [absolute, workspaceId, nonce, reload]);

  if (!file) {
    return <div data-testid="side-file-tab" className="h-full">
      <Notice message={t("ide_side_panel.file.empty")} />
    </div>;
  }

  const clean = absolute.replace(/\\/g, "/");
  const cut = clean.lastIndexOf("/");
  const name = cut < 0 ? clean : clean.slice(cut + 1);
  const folder = cut < 0 ? "" : clean.slice(0, cut + 1);
  const hasChange = Boolean(file.diff?.length);
  const shown = view === "change" && hasChange ? "change" : "file";
  const language = loaded.state === "ready" && loaded.text.length <= HIGHLIGHT_MAX_CHARS ? fileLanguage(name) : "";
  const tabButton = (id: "file" | "change", label: string) => <button type="button" role="tab" aria-selected={shown === id}
    onClick={() => setView(id)}
    className={cn("rounded-md px-2 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      shown === id ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}>{label}</button>;

  return <section data-testid="side-file-tab" aria-label={t("ide_side_panel.tabs.file")} className="flex h-full min-h-0 flex-col">
    <header className="flex items-center gap-2 border-b border-border px-3 py-2">
      <FileCode2 aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="flex min-w-0 flex-1 text-sm" title={absolute}>
        {/* The folder gives way first, cut from its left, so the name stays readable. */}
        {folder && <span dir="rtl" className="min-w-0 shrink-[999] truncate text-left text-muted-foreground"><bdi dir="ltr">{folder}</bdi></span>}
        <span className="min-w-0 max-w-full shrink-0 truncate font-medium text-foreground" data-testid="side-file-name">{name}</span>
      </span>
      {hasChange && <div role="tablist" aria-label={t("ide_side_panel.file.views")} className="flex shrink-0 items-center gap-0.5">
        {tabButton("file", t("ide_side_panel.file.view_file"))}
        {tabButton("change", t("ide_side_panel.file.view_change"))}
      </div>}
      <button type="button" aria-label={t("ide_side_panel.file.reload")} title={t("ide_side_panel.file.reload")}
        onClick={() => setReload((value) => value + 1)}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <RefreshCw aria-hidden className="h-3.5 w-3.5" />
      </button>
    </header>
    <div className="min-h-0 flex-1 overflow-auto scrollbar-jarvis" data-testid="side-file-body" data-view={shown}>
      {shown === "change"
        ? <DiffView files={file.diff ?? []} className="p-3 [&_pre]:max-h-none" />
        : loaded.state === "loading"
          ? <div className="flex h-full items-center justify-center"><Loader2 aria-label={t("ide_side_panel.file.loading")} className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          : loaded.state === "ready"
            ? <div className="select-text [&_.code-block-body]:text-xs [&_.code-block-body]:leading-5 [&_pre]:text-xs [&_pre]:leading-5">
              <CodeBlock language={language} code={loaded.text} chrome={false} />
            </div>
            : <Notice message={t(`ide_side_panel.file.${loaded.state}`)}>
              {hasChange && <button type="button" onClick={() => setView("change")}
                className="rounded-md border border-border px-3 py-1 text-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {t("ide_side_panel.file.show_change")}
              </button>}
            </Notice>}
    </div>
  </section>;
}
