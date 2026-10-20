import { EDITOR_OPTIONS, monaco } from "./monacoRuntime";
import { clampFollowTop, followColumnOf, followOffset, followStep } from "./followLayout";

type CodeEditor = monaco.editor.IStandaloneCodeEditor;

/**
 * What every column turns off while follow mode is on. A minimap or a
 * sticky header would take lines out of the text, and a folded region in one
 * column would shift every column after it. Scrolling is immediate: an
 * animated scroll would still be moving the columns after a cursor has
 * already been handed to the next one.
 */
const FOLLOW_OPTIONS: monaco.editor.IEditorOptions = {
  minimap: { enabled: false },
  stickyScroll: { enabled: false },
  folding: false,
  smoothScrolling: false,
};

/** The lead editor's own settings, put back when follow mode ends. */
const LEAD_RESTORE: monaco.editor.IEditorOptions = {
  minimap: EDITOR_OPTIONS.minimap,
  stickyScroll: EDITOR_OPTIONS.stickyScroll,
  folding: true,
  smoothScrolling: EDITOR_OPTIONS.smoothScrolling,
};

export interface FollowColumns {
  /** The columns after the lead one, left to right. */
  editors: CodeEditor[];
  dispose(): void;
}

/**
 * Follow mode: the file in `lead` continues in `hosts.length` more columns.
 *
 * Every column edits the same text. Scrolling any of them scrolls the whole
 * surface, and a cursor that walks off the bottom (or top) of a column with
 * the keyboard carries on in the next (or previous) column instead of
 * scrolling the text under it.
 */
export function followColumns(lead: CodeEditor, hosts: HTMLElement[]): FollowColumns {
  const columns: CodeEditor[] = [lead];
  for (const host of hosts) {
    columns.push(
      monaco.editor.create(host, {
        ...EDITOR_OPTIONS,
        ...FOLLOW_OPTIONS,
        // A later column of a short file scrolls past the file's end.
        scrollBeyondLastLine: true,
        model: lead.getModel(),
        theme: "jarvis",
      }),
    );
  }
  lead.updateOptions(FOLLOW_OPTIONS);

  const lineHeight = () => lead.getOption(monaco.editor.EditorOption.lineHeight);
  // The text a column shows: the horizontal scrollbar covers its bottom edge.
  const viewport = () => {
    const layout = lead.getLayoutInfo();
    return layout.height - layout.horizontalScrollbarHeight;
  };
  // The blank space above the first line, which only the first column shows.
  const above = () => lead.getOption(monaco.editor.EditorOption.padding).top;
  const step = () => followStep(viewport(), lineHeight(), above());
  // Where the last line ends, without the blank space below it.
  const textEnd = () => lead.getContentHeight() - lead.getOption(monaco.editor.EditorOption.padding).bottom;

  // The first column's scroll offset; the others follow it (see followLayout).
  let top = lead.getScrollTop();
  let applying = false;

  const apply = () => {
    const room = step();
    const space = above();
    const end = textEnd();
    applying = true;
    try {
      columns.forEach((editor, index) => {
        const wanted = followOffset(top, index, room, space);
        if (Math.abs(editor.getScrollTop() - wanted) > 0.5) editor.setScrollTop(wanted, monaco.editor.ScrollType.Immediate);
        // A column that starts below the file's end stays empty.
        if (index > 0) editor.getDomNode()!.style.visibility = wanted >= end ? "hidden" : "";
      });
    } finally {
      applying = false;
    }
  };

  const moveTo = (next: number) => {
    top = clampFollowTop(next, lead.getContentHeight(), viewport(), step(), columns.length, above());
    apply();
  };

  const watchers: monaco.IDisposable[] = [];
  columns.forEach((editor, index) => {
    watchers.push(
      editor.onDidScrollChange((event) => {
        if (applying || !event.scrollTopChanged) return;
        moveTo(event.scrollTop - followOffset(0, index, step(), above()));
      }),
      editor.onDidChangeCursorSelection((event) => {
        // Only the keyboard walks the cursor from column to column; a click
        // or a jump to a line lands where it was asked to.
        if (event.source !== "keyboard" || !editor.hasTextFocus()) return;
        const before = top;
        // The cursor's own row: a wrapped line spans several rows, and the
        // cursor may sit on any of them.
        const row = editor.getScrolledVisiblePosition(event.selection.getPosition());
        if (!row) return;
        const target = followColumnOf(row.top + editor.getScrollTop(), before, step(), columns.length, above());
        if (target === null) return;
        // The editor scrolls its cursor into view right after this event
        // (with a line of air below it). The line is on the surface already,
        // so that scroll is undone once it has happened.
        queueMicrotask(() => {
          if (Math.abs(top - before) > 0.5) moveTo(before);
          if (target === index) return;
          const next = columns[target];
          next.setSelections(editor.getSelections() ?? [event.selection]);
          next.focus();
        });
      }),
    );
  });
  watchers.push(
    // A new tab in the lead editor shows in every column, from its own scroll offset.
    lead.onDidChangeModel(() => {
      const model = lead.getModel();
      for (const editor of columns.slice(1)) editor.setModel(model);
      moveTo(lead.getScrollTop());
    }),
    lead.onDidLayoutChange(() => moveTo(top)),
    lead.onDidContentSizeChange(() => moveTo(top)),
  );

  moveTo(top);

  let disposed = false;
  return {
    editors: columns.slice(1),
    dispose() {
      // The surface ends follow mode both when it is turned off and when the
      // lead editor goes away; only the first call acts.
      if (disposed) return;
      disposed = true;
      for (const watcher of watchers) watcher.dispose();
      for (const editor of columns.slice(1)) editor.dispose();
      lead.updateOptions(LEAD_RESTORE);
    },
  };
}
