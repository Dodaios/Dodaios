import { useEffect, useRef, useState, type MouseEvent } from "react";

import { SaveConflictError, saveTextFile, type LineEnding } from "@/components/agentic/editor/editorApi";
import { languageFor } from "@/components/agentic/editor/editorModels";
import { EDITOR_OPTIONS, applyTheme, monaco } from "@/components/agentic/editor/monacoRuntime";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { discardDraft, getDraft, setDraft } from "./fileDrafts";

/** What the editor hands back once a save reached the disk, so the tab's own copy stays current. */
export interface SavedFile {
  text: string;
  version: string;
  encoding: string;
  eol: LineEnding;
}

// Monaco draws its own context menu; the app-wide edit menu must not open on top.
const keepContextMenu = (event: MouseEvent) => event.stopPropagation();

type Status = "idle" | "saving" | "conflict" | "error";

/**
 * The File tab's editor: the file as text that can be changed and saved
 * (Ctrl/Cmd+S or the Save button), on the same engine as the code editor.
 *
 * A save names the disk version the text was based on, so a file an agent
 * changed in the meantime is never overwritten by accident: the person is
 * asked whether to overwrite it or to read the disk's text instead.
 */
export default function FileEditor({
  workspaceId,
  path,
  text,
  version,
  encoding,
  eol,
  line,
  onSaved,
  onReload,
}: {
  workspaceId: string;
  /** The path the server reads and writes the file by. */
  path: string;
  text: string;
  version: string;
  encoding: string;
  eol: LineEnding;
  /** The line the click pointed at; the editor opens there. */
  line?: number;
  onSaved: (saved: SavedFile) => void;
  /** Read the file from disk again, dropping the unsaved text. */
  onReload: () => void;
}) {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  // What the disk held when this text was read or last saved.
  const base = useRef({ text, version, encoding });
  // The model's version id at that point: dirty is "different from it", so undo clears the mark.
  const savedId = useRef(0);
  const diskVersion = useRef<string | null>(null);
  const saving = useRef(false);
  const callbacks = useRef({ onSaved });
  callbacks.current = { onSaved };
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const save = useRef<(overwrite?: boolean) => Promise<void>>(async () => {});

  save.current = async (overwrite = false) => {
    const model = editorRef.current?.getModel();
    if (!model || saving.current) return;
    saving.current = true;
    setStatus("saving");
    const sent = model.getAlternativeVersionId();
    const value = model.getValue();
    try {
      const saved = await saveTextFile(workspaceId, {
        path,
        text: value,
        expectedVersion: overwrite ? diskVersion.current : base.current.version,
        encoding: base.current.encoding,
        // Overwriting a file that was deleted meanwhile writes it again.
        create: overwrite && diskVersion.current === null,
      });
      base.current = { text: value, version: saved.version, encoding: saved.encoding };
      savedId.current = sent;
      diskVersion.current = null;
      setDirty(model.getAlternativeVersionId() !== sent);
      if (model.getAlternativeVersionId() === sent) discardDraft(workspaceId, path);
      setStatus("idle");
      callbacks.current.onSaved({ text: value, version: saved.version, encoding: saved.encoding, eol: saved.eol });
    } catch (failure) {
      if (failure instanceof SaveConflictError) {
        diskVersion.current = failure.currentVersion;
        setStatus("conflict");
      } else {
        setError((failure as Error).message);
        setStatus("error");
      }
    } finally {
      saving.current = false;
    }
  };

  // Follow the app's light/dark switch, as the code editor does.
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => applyTheme(root.classList.contains("dark"));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["class", "style"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!host.current) return;
    applyTheme(document.documentElement.classList.contains("dark"));
    const model = monaco.editor.createModel(
      text,
      languageFor(path),
      monaco.Uri.from({ scheme: "jarvis-side-file", path: `/${encodeURIComponent(workspaceId)}/${path}` }),
    );
    // Text without a line break says nothing about its line ending; set it
    // before the saved marker is taken so a fresh load is never dirty.
    model.setEOL(eol === "\r\n" ? monaco.editor.EndOfLineSequence.CRLF : monaco.editor.EndOfLineSequence.LF);
    savedId.current = model.getAlternativeVersionId();

    const draft = getDraft(workspaceId, path);
    if (draft && draft.text !== text) {
      model.pushEditOperations([], [{ range: model.getFullModelRange(), text: draft.text }], () => null);
      model.pushStackElement();
      // The disk moved on while the edits waited: they are not based on what is there now.
      if (draft.version !== version) {
        diskVersion.current = version;
        setStatus("conflict");
      }
    }
    const track = () => {
      const changed = model.getAlternativeVersionId() !== savedId.current;
      setDirty(changed);
      if (changed) setDraft(workspaceId, path, { text: model.getValue(), version: base.current.version });
      else discardDraft(workspaceId, path);
    };
    track();
    const listener = model.onDidChangeContent(track);

    const editor = monaco.editor.create(host.current, {
      ...EDITOR_OPTIONS,
      model,
      theme: "jarvis",
      readOnly: false,
      // A narrow side panel has no room for either.
      minimap: { enabled: false },
      stickyScroll: { enabled: false },
    });
    editorRef.current = editor;
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => void save.current());
    if (line && line > 0) {
      const target = Math.min(line, model.getLineCount());
      editor.setPosition({ lineNumber: target, column: 1 });
      editor.revealLineInCenter(target);
    }
    return () => {
      listener.dispose();
      editor.dispose();
      model.dispose();
      editorRef.current = null;
    };
    // The editor is built once for the text it was given; a save keeps it, a reload remounts it.
  }, []);

  const showBar = dirty || status !== "idle";
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="side-file-editor">
      {showBar && (
        <div
          role="status"
          data-testid="side-file-editor-bar"
          className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-1.5 text-xs text-muted-foreground"
        >
          <span className="min-w-0 flex-1">
            {status === "conflict"
              ? t("ide_side_panel.file.conflict")
              : status === "error"
                ? fill(t("ide_side_panel.file.save_failed"), { error })
                : status === "saving"
                  ? t("ide_side_panel.file.saving")
                  : t("ide_side_panel.file.unsaved")}
          </span>
          {status === "conflict" ? (
            <>
              <BarButton onClick={() => void save.current(true)}>{t("ide_side_panel.file.overwrite")}</BarButton>
              <BarButton onClick={onReload}>{t("ide_side_panel.file.discard")}</BarButton>
            </>
          ) : (
            <BarButton disabled={status === "saving"} primary onClick={() => void save.current()}>
              {t("ide_side_panel.file.save")}
            </BarButton>
          )}
        </div>
      )}
      <div ref={host} onContextMenu={keepContextMenu} data-testid="side-file-editor-host" className="min-h-0 flex-1" />
    </div>
  );
}

function BarButton({
  children,
  onClick,
  disabled,
  primary,
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-md border border-border px-2 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        primary ? "bg-secondary text-foreground hover:bg-secondary/70" : "text-foreground hover:bg-secondary",
      )}
    >
      {children}
    </button>
  );
}
