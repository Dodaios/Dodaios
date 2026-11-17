/**
 * The contract between the stage and a node type's native editor.
 *
 * The stage (`views/VisualizationView.tsx`) reads the node's spec once
 * (`GET /api/nodes/{id}`), mounts the type's editor from `registry.ts` with
 * that spec as `initial`, and calls `onDone` when the person closes it again.
 * Everything in between (the edits, undo and redo, saving, a revision the
 * assistant writes meanwhile) is the editor's business, done through
 * `useNodeSpecEditor` and framed by `EditorShell`.
 */
import type { ComponentType } from "react";

import type { NodeCard } from "../nodeModel";

/** The node types edited in a native editor (a whiteboard has its own canvas). */
export const EDITABLE_TYPES = ["docs", "slides", "sheets", "data", "motion"] as const;

export type EditableType = (typeof EDITABLE_TYPES)[number];

export function isEditableType(value: unknown): value is EditableType {
  return typeof value === "string" && (EDITABLE_TYPES as readonly string[]).includes(value);
}

/** The spec as the server last saved it, and which revision that was. */
export interface NodeEditorInitial {
  spec: unknown;
  version: number;
  /** Seconds since the epoch. */
  updated_at: number;
}

/**
 * Where the reader clicked into the node's page to open the editor: the place
 * in the spec (a JSON Pointer) and the drawn words right before and after the
 * click. An editor that can find the spot puts its caret there.
 */
export interface NodeEditorStart {
  path: string;
  before: string;
  after: string;
}

export interface NodeEditorProps {
  /** The typed node being edited (its `id` is never null here). */
  node: NodeCard;
  initial: NodeEditorInitial;
  /** The editor was opened by a click into the page: where. Absent after "Edit". */
  startAt?: NodeEditorStart | null;
  /** Leave the editor: the stage shows the node's page again, drawn from the saved spec. */
  onDone: () => void;
}

/** What `registry.ts` loads for a type: a module whose default export is the editor. */
export interface NodeEditorModule {
  default: ComponentType<NodeEditorProps>;
}
