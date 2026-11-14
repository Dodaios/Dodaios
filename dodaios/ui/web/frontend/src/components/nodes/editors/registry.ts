/**
 * Which editor opens for which node type.
 *
 * Every editor is its own lazy chunk: the stage only downloads the code of
 * the type being edited, and a reader who never presses "Edit" downloads
 * none. Each type owns its folder (`./<type>/index.tsx`); this table only
 * points at them, so nobody but the foundation edits it.
 */
import type { EditableType, NodeEditorModule } from "./types";

export const NODE_EDITORS: Record<EditableType, () => Promise<NodeEditorModule>> = {
  docs: () => import("./docs/index"),
  slides: () => import("./slides/index"),
  sheets: () => import("./sheets/index"),
  design: () => import("./design/index"),
  data: () => import("./data/index"),
  motion: () => import("./motion/index"),
};

export { EDITABLE_TYPES, isEditableType } from "./types";
export type { EditableType, NodeEditorModule, NodeEditorProps } from "./types";
