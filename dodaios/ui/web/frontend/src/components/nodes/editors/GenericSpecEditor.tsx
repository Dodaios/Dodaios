/**
 * The fallback editor: the spec as formatted JSON, edited as a whole.
 *
 * It stands in for a type until that type's own editor exists, and is a
 * plain way to check the shared machinery (undo, saving, conflicts) end to
 * end. Text that is not valid JSON stays in the field with a note and is
 * not applied; valid JSON becomes one undo step per typing run.
 */
import { useEffect, useState } from "react";

import { useT } from "@/i18n";
import { EditorShell } from "./EditorShell";
import type { NodeEditorProps } from "./types";
import { useNodeSpecEditor } from "./useNodeSpecEditor";

export function GenericSpecEditor({ node, initial, onDone }: NodeEditorProps) {
  const t = useT();
  const editor = useNodeSpecEditor<unknown>(node.id ?? "", initial);
  const [text, setText] = useState(() => JSON.stringify(editor.spec, null, 2));
  const [invalid, setInvalid] = useState(false);
  // Undo, redo and a revision from the server put their spec in the field.
  useEffect(() => {
    let current: unknown;
    try {
      current = JSON.parse(text);
    } catch {
      current = undefined;
    }
    if (JSON.stringify(current) !== JSON.stringify(editor.spec)) {
      setText(JSON.stringify(editor.spec, null, 2));
      setInvalid(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor.spec]);
  return (
    <EditorShell editor={editor} title={node.title} onDone={onDone} bodyClassName="flex flex-col p-4">
      <label className="mb-2 text-sm text-muted-foreground" htmlFor="node-generic-spec">
        {t("nodes.editor.generic.label")}
      </label>
      <textarea
        id="node-generic-spec"
        data-spec-undo=""
        spellCheck={false}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          try {
            const parsed = JSON.parse(event.target.value) as unknown;
            setInvalid(false);
            editor.apply(() => parsed, { label: t("nodes.editor.generic.step"), coalesce: "generic" });
          } catch {
            setInvalid(true);
          }
        }}
        className="min-h-0 flex-1 resize-none rounded-md border border-border-strong bg-input p-3 font-mono text-sm text-foreground focus-visible:border-accent focus-visible:outline-none"
      />
      {invalid && (
        <p role="status" className="mt-2 text-sm text-warning">
          {t("nodes.editor.generic.invalid")}
        </p>
      )}
    </EditorShell>
  );
}
