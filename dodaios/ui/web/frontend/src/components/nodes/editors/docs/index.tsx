/**
 * The document editor: a rich-text editor on a docs node's Markdown.
 *
 * The person edits the document as it reads (headings, lists, tables,
 * callouts, charts, pictures) and never sees Markdown, except for the rare
 * shapes only the page's renderer knows, which stay editable as text. The
 * spec the assistant reads and writes stays plain Markdown: every change is
 * written back through `DocSession` (untouched blocks keep their exact text,
 * see `markdown/document.ts`) and saved by the shared `useNodeSpecEditor`.
 *
 * Undo and redo are the text editor's own history (it knows the caret and
 * groups typing by pauses); the frame's buttons and shortcuts are pointed at
 * it, so there is one history for the whole document, summary included. The
 * spec hook still owns saving, conflicts and the assistant's revisions: a
 * revision that arrives while nothing is unsaved replaces the content (one
 * undo step brings the person's version back).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { EditorContent, ReactNodeViewRenderer, useEditor, useEditorState, type Editor } from "@tiptap/react";
import type { EditorView } from "@tiptap/pm/view";

import { useT } from "@/i18n";
import { EditorShell } from "../EditorShell";
import type { NodeEditorProps } from "../types";
import { hasOwnUndo, shortcutOf, useNodeSpecEditor, type NodeSpecEditor } from "../useNodeSpecEditor";
import { DocSession, MAX_BODY_CHARS, cleanSummary, readSpec, type DocsSpec } from "./docModel";
import { docExtensions } from "./extensions";
import { pictureFiles, pictureFromFile } from "./images";
import { Outline } from "./Outline";
import { DocsToolbar } from "./Toolbar";
import { CalloutView } from "./views/CalloutView";
import { ChartBlockView } from "./views/ChartBlockView";
import { MetricsBlockView } from "./views/MetricsBlockView";
import "./docs.css";

/** Room kept free in the body for the picture's own Markdown and later typing. */
const PICTURE_HEADROOM = 2_000;
const NOTICE_MS = 6_000;

export default function DocsEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const prepare = useCallback(
    (value: DocsSpec): DocsSpec | { error: string } => {
      // The server refuses a document without a body and clips one past its
      // limit; holding the save with a sentence is kinder than either.
      if (!value.markdown.trim()) return { error: t("nodes.editor.docs.errors.empty") };
      if (value.markdown.length > MAX_BODY_CHARS) return { error: t("nodes.editor.docs.errors.too_long") };
      return value;
    },
    [t],
  );
  const specEditor = useNodeSpecEditor<DocsSpec>(node.id ?? "", initial, { prepare });
  const specRef = useRef(specEditor);
  specRef.current = specEditor;

  const sessionRef = useRef<DocSession | null>(null);
  sessionRef.current ??= new DocSession(readSpec(initial.spec));
  /** The spec object this editor last handed to the hook (or loaded). */
  const lastApplied = useRef<unknown>(initial.spec);

  const [linkOpen, setLinkOpen] = useState(false);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const editorRef = useRef<Editor | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /** Put picture files into the document at `at` (or the caret), each scaled to fit. */
  const insertPictures = useCallback(
    async (files: File[], at?: number) => {
      for (const file of files) {
        const current = editorRef.current;
        if (!current) return;
        const used = sessionRef.current!.specOf(current.state.doc).markdown.length;
        const result = await pictureFromFile(file, MAX_BODY_CHARS - used - PICTURE_HEADROOM);
        const target = editorRef.current;
        if (!target || target.isDestroyed) return;
        if (!result.ok) {
          setNotice(t(`nodes.editor.docs.picture.${result.reason}`));
          continue;
        }
        const alt = file.name.replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || null;
        const content = { type: "image", attrs: { src: result.src, alt } };
        if (at !== undefined) target.chain().focus().insertContentAt(at, content).run();
        else target.chain().focus().insertContent(content).run();
      }
    },
    [t],
  );

  const extensions = useMemo(
    () =>
      docExtensions({
        views: {
          callout: ReactNodeViewRenderer(CalloutView),
          chart: ReactNodeViewRenderer(ChartBlockView),
          metrics: ReactNodeViewRenderer(MetricsBlockView),
        },
        placeholders: {
          summary: t("nodes.editor.docs.placeholder.summary"),
          body: t("nodes.editor.docs.placeholder.body"),
          heading: t("nodes.editor.docs.placeholder.heading"),
        },
        labels: { raw: t("nodes.editor.docs.raw"), pictureNotLoaded: t("nodes.editor.docs.picture.not_loaded") },
        onLink: () => setLinkOpen(true),
      }),
    // The schema is built once per editor; labels are read when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  /** The document changed: hand its spec to the hook, which saves it. */
  const push = useCallback(
    (current: Editor) => {
      const next = sessionRef.current!.specOf(current.state.doc);
      const present = readSpec(specRef.current.spec);
      if (next.summary === cleanSummary(present.summary) && next.markdown === present.markdown) return;
      lastApplied.current = next;
      specRef.current.apply(() => next, { label: t("nodes.editor.docs.step"), coalesce: "docs" });
    },
    [t],
  );

  const editor = useEditor({
    extensions,
    content: sessionRef.current.content,
    immediatelyRender: true,
    shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: {
        class: "doc-editor-content",
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": t("nodes.editor.docs.body"),
        "data-testid": "docs-editor-content",
      },
      handlePaste: (_view: EditorView, event: ClipboardEvent) => {
        const files = pictureFiles(event.clipboardData?.files);
        if (!files.length) return false;
        event.preventDefault();
        void insertPictures(files);
        return true;
      },
      handleDrop: (view: EditorView, event: DragEvent, _slice: unknown, moved: boolean) => {
        if (moved) return false;
        const files = pictureFiles(event.dataTransfer?.files);
        if (!files.length) return false;
        event.preventDefault();
        const at = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos;
        void insertPictures(files, at);
        return true;
      },
    },
    onUpdate: ({ editor: current }) => push(current),
  });
  editorRef.current = editor;

  // Pair the loaded blocks with their Markdown once the editor holds them.
  useEffect(() => {
    if (editor) sessionRef.current!.remember(editor.state.doc);
  }, [editor]);

  // A spec that did not come from this editor (the assistant's revision, or
  // "Take theirs") replaces the content.
  useEffect(() => {
    if (!editor || specEditor.spec === lastApplied.current) return;
    lastApplied.current = specEditor.spec;
    const next = readSpec(specEditor.spec);
    const mine = sessionRef.current!.specOf(editor.state.doc);
    if (mine.summary === cleanSummary(next.summary) && mine.markdown === next.markdown) return;
    const session = new DocSession(next);
    sessionRef.current = session;
    editor.commands.setContent(session.content, { emitUpdate: false });
    session.remember(editor.state.doc);
  }, [editor, specEditor.spec]);

  const history = useEditorState({
    editor,
    selector: ({ editor: current }) => ({ canUndo: current.can().undo(), canRedo: current.can().redo() }),
  });

  /** The hook's state with the frame's undo/redo pointed at the text editor's history. */
  const shellEditor: NodeSpecEditor<DocsSpec> = useMemo(() => {
    const undo = () => void editor.chain().focus().undo().run();
    const redo = () => void editor.chain().focus().redo().run();
    return {
      ...specEditor,
      undo,
      redo,
      canUndo: history.canUndo,
      canRedo: history.canRedo,
      undoLabel: null,
      redoLabel: null,
      history: { undo: [], redo: [] },
      onKeyDown: (event: ReactKeyboardEvent | KeyboardEvent) => {
        const wanted = shortcutOf(event);
        // Inside the text the editor's own keymap already answered.
        if (wanted === null || event.defaultPrevented || hasOwnUndo(event.target)) return;
        event.preventDefault();
        event.stopPropagation();
        if (wanted === "undo") undo();
        else redo();
      },
    };
  }, [editor, specEditor, history.canUndo, history.canRedo]);

  return (
    <EditorShell
      editor={shellEditor}
      title={node.title}
      onDone={onDone}
      toolbar={
        <DocsToolbar
          editor={editor}
          linkOpen={linkOpen}
          onLinkOpenChange={setLinkOpen}
          outlineOpen={outlineOpen}
          onOutlineToggle={() => setOutlineOpen((open) => !open)}
          onPickPicture={() => fileInput.current?.click()}
        />
      }
      side={outlineOpen ? <Outline editor={editor} /> : undefined}
    >
      <div
        className="doc-editor mx-auto w-full max-w-[816px] px-12 pb-40 pt-12"
        onMouseDown={(event) => {
          // A click in the margin below the text puts the caret at the end.
          if (event.target === event.currentTarget) {
            event.preventDefault();
            editor.commands.focus("end");
          }
        }}
        data-testid="docs-editor"
      >
        <h1 className="doc-title">{node.title}</h1>
        <EditorContent editor={editor} />
        {notice && (
          <p role="status" className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-border bg-popover px-4 py-2 text-sm text-popover-foreground shadow-float">
            {notice}
          </p>
        )}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        multiple
        hidden
        onChange={(event) => {
          const files = pictureFiles(event.target.files);
          event.target.value = "";
          if (files.length) void insertPictures(files);
        }}
        data-testid="docs-picture-input"
      />
    </EditorShell>
  );
}
