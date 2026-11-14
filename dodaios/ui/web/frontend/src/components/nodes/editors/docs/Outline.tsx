/**
 * The document's outline: its headings, indented by level, the one the caret
 * is in marked. A click (or Enter) puts the caret at that heading and scrolls
 * it into view.
 */
import { useEditorState, type Editor } from "@tiptap/react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

export interface OutlineEntry {
  pos: number;
  level: number;
  text: string;
}

/** The body's top-level headings, in order (a heading in a quote is not a section). */
export function outlineOf(editor: Editor): OutlineEntry[] {
  const entries: OutlineEntry[] = [];
  editor.state.doc.forEach((node, offset) => {
    if (node.type.name === "heading" && node.textContent.trim()) {
      entries.push({ pos: offset, level: Number(node.attrs.level) || 2, text: node.textContent.trim() });
    }
  });
  return entries;
}

export function Outline({ editor }: { editor: Editor }) {
  const t = useT();
  const { entries, current } = useEditorState({
    editor,
    selector: ({ editor: e }) => {
      const list = outlineOf(e);
      const caret = e.state.selection.from;
      let at = -1;
      list.forEach((entry, index) => {
        if (entry.pos <= caret) at = index;
      });
      return { entries: list, current: at };
    },
  });
  const top = Math.min(...entries.map((entry) => entry.level), 6);
  return (
    <nav aria-label={t("nodes.editor.docs.outline.label")} data-testid="docs-outline">
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {t("nodes.editor.docs.outline.label")}
      </h2>
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("nodes.editor.docs.outline.empty")}</p>
      ) : (
        <ol className="space-y-0.5">
          {entries.map((entry, index) => (
            <li key={`${entry.pos}-${index}`}>
              <button
                type="button"
                aria-current={index === current ? "location" : undefined}
                onClick={() => editor.chain().focus().setTextSelection(entry.pos + 1).scrollIntoView().run()}
                className={cn(
                  "block w-full truncate rounded-md py-1 pr-2 text-left text-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  index === current ? "font-medium text-foreground" : "text-muted-foreground",
                )}
                style={{ paddingLeft: `${8 + Math.max(0, entry.level - top) * 12}px` }}
              >
                {entry.text}
              </button>
            </li>
          ))}
        </ol>
      )}
    </nav>
  );
}
