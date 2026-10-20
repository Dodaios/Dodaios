import { useEffect, useRef } from "react";
import { EDITOR_OPTIONS, applyTheme, monaco } from "../../../editor/monacoRuntime";
import { languageFor } from "../../../editor/editorModels";

/**
 * A read-only side-by-side diff of two texts (a commit's change to one file).
 * Loaded lazily with the editor engine, never on the app's boot path.
 */
export default function MonacoDiff({ path, before, after }: { path: string; before: string; after: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => applyTheme(root.classList.contains("dark"));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["class", "style"] });
    const language = languageFor(path);
    const original = monaco.editor.createModel(before, language);
    const modified = monaco.editor.createModel(after, language);
    const diff = monaco.editor.createDiffEditor(host.current!, {
      ...EDITOR_OPTIONS,
      minimap: { enabled: false },
      stickyScroll: { enabled: false },
      readOnly: true,
      originalEditable: false,
      renderSideBySide: true,
      useInlineViewWhenSpaceIsLimited: true,
      renderSideBySideInlineBreakpoint: 700,
      theme: "jarvis",
    });
    diff.setModel({ original, modified });
    return () => {
      observer.disconnect();
      diff.dispose();
      original.dispose();
      modified.dispose();
    };
  }, [path, before, after]);
  return <div ref={host} data-testid="scm-diff-editor" className="h-full w-full" />;
}
