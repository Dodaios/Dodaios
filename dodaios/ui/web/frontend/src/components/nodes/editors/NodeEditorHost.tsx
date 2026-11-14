/**
 * The stage's side of a node editor: load the spec, load the type's editor,
 * and feed it the node's revisions.
 *
 * "Edit" on the stage swaps the node's page for this. It reads the node's
 * spec (`GET /api/nodes/{id}`), downloads the type's editor chunk
 * (`registry.ts`), and keeps the node's watcher (`NodeUpkeepBar`, the same
 * strip the page has) running, its reports handed to the editor through
 * `RevisionContext`, so what the assistant writes meanwhile reaches the open
 * editor. An editor that fails to load or crashes shows a plain message with
 * the way back to the page; the person's saved work is on the server either
 * way.
 */
import { Component, Suspense, lazy, useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useLocaleChunk, useT } from "@/i18n";
import type { NodeCard } from "../nodeModel";
import { invalidateNodes } from "../useNodes";
import { fetchNodeSpec } from "./api";
import { RevisionContext, createRevisionSource } from "./editorContext";
import { NODE_EDITORS } from "./registry";
import type { EditableType, NodeEditorInitial, NodeEditorProps } from "./types";

const NodeUpkeepBar = lazy(() => import("../NodeUpkeepBar"));

/** One lazy component per type, made once, so a second Edit reuses the loaded chunk. */
const LAZY_EDITORS = new Map<EditableType, ComponentType<NodeEditorProps>>();

export function editorComponent(type: EditableType): ComponentType<NodeEditorProps> {
  let found = LAZY_EDITORS.get(type);
  if (!found) {
    found = lazy(NODE_EDITORS[type]);
    LAZY_EDITORS.set(type, found);
  }
  return found;
}

class EditorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error("node editor crashed", error);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export interface NodeEditorHostProps {
  node: NodeCard & { id: string };
  type: EditableType;
  /** The node's run slug, for its watcher. */
  slug: string;
  /** Back to the page. */
  onDone: () => void;
}

export default function NodeEditorHost({ node, type, slug, onDone }: NodeEditorHostProps) {
  const t = useT();
  // The editors' words are their own locale chunk, kept out of the startup
  // bundle; an editor is drawn once they are in.
  const strings = useLocaleChunk("node_editors");
  const client = useQueryClient();
  const [load, setLoad] = useState<{ state: "loading" | "ready" | "failed"; initial: NodeEditorInitial | null }>({
    state: "loading",
    initial: null,
  });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoad({ state: "loading", initial: null });
    fetchNodeSpec(node.id, controller.signal)
      .then((saved) => setLoad({ state: "ready", initial: saved }))
      .catch(() => {
        if (!controller.signal.aborted) setLoad({ state: "failed", initial: null });
      });
    return () => controller.abort();
  }, [node.id, attempt]);

  const source = useMemo(() => createRevisionSource(), [node.id]);
  const Editor = editorComponent(type);
  const done = useCallback(() => {
    // The library's card and cover follow the saved content.
    invalidateNodes(client);
    onDone();
  }, [client, onDone]);

  const waiting = (
    <div className="flex h-full items-center justify-center gap-2 text-base text-muted-foreground" data-testid="node-editor-loading">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t("nodes.editor.loading")}
    </div>
  );
  const failed = (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center" data-testid="node-editor-failed">
      <p className="max-w-sm text-base text-muted-foreground">{t("nodes.editor.load_failed")}</p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
          {t("nodes.editor.retry")}
        </Button>
        <Button size="sm" onClick={onDone}>
          {t("nodes.editor.done")}
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex h-full flex-col" data-testid="visualization-node-editor" data-type={type}>
      <Suspense fallback={null}>
        <NodeUpkeepBar slug={slug} onUpdated={source.emit} />
      </Suspense>
      <div className="min-h-0 flex-1">
        {(load.state === "loading" || (load.state === "ready" && !strings)) && waiting}
        {load.state === "failed" && failed}
        {load.state === "ready" && strings && load.initial !== null && (
          <RevisionContext.Provider value={source}>
            <EditorBoundary fallback={failed}>
              <Suspense fallback={waiting}>
                <Editor key={node.id} node={node} initial={load.initial} onDone={done} />
              </Suspense>
            </EditorBoundary>
          </RevisionContext.Provider>
        )}
      </div>
    </div>
  );
}
