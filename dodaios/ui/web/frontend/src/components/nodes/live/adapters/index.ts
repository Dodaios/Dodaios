/**
 * Which reveal plays for which node type. Each type owns its file here; this
 * table only points at them, so a type's reveal changes without touching it.
 */
import type { NodeType } from "../../nodeModel";
import type { RevealAdapter } from "../reveal";
import { dataReveal } from "./data";
import { docsReveal } from "./docs";
import { motionReveal } from "./motion";
import { sheetsReveal } from "./sheets";
import { slidesReveal } from "./slides";
import { whiteboardReveal } from "./whiteboard";

export const REVEAL_ADAPTERS: Record<NodeType, RevealAdapter> = {
  docs: docsReveal,
  slides: slidesReveal,
  sheets: sheetsReveal,
  data: dataReveal,
  whiteboard: whiteboardReveal,
  motion: motionReveal,
};

export function revealAdapter(type: NodeType): RevealAdapter {
  return REVEAL_ADAPTERS[type];
}
