/**
 * The "new agent" dialog, opened from every plus in the society (the Agents
 * page, the office's reception, the foundry) and from the marketplace's
 * template import. `request()` opens it and settles once the person created
 * an agent — or rejects with `CreateAgentCancelled` when they closed it — so
 * each plus keeps its own "then open the new agent's chat" step.
 */
import { create } from "zustand";
import type { SocietyAgent } from "../data";

export class CreateAgentCancelled extends Error {
  constructor() {
    super("Agent creation cancelled");
    this.name = "CreateAgentCancelled";
  }
}

/** The dialog's three ways in: blank, a starter from the gallery, an imported template. */
export type CreateAgentMode = "quick" | "starter" | "import";

export interface CreateAgentRequest {
  /** Which path the dialog opens on; blank by default. */
  mode?: CreateAgentMode;
  /** A template to preview straight away (opens on the import path). */
  template?: Record<string, unknown>;
}

interface CreateAgentDialogState {
  open: boolean;
  /** What the current request asked the dialog to open on. */
  initial: CreateAgentRequest;
  /** Counts requests that bring their own starting point (a template, a
   *  path): those start from a fresh form, a plain second plus keeps it. */
  requestId: number;
  request: (options?: CreateAgentRequest) => Promise<SocietyAgent>;
  /** The dialog created the agent: settle the pending request. */
  finish: (agent: SocietyAgent) => void;
  cancel: () => void;
}

let pending: { resolve: (agent: SocietyAgent) => void; reject: (error: Error) => void } | null = null;

export const useCreateAgentDialog = create<CreateAgentDialogState>((set) => ({
  open: false,
  initial: {},
  requestId: 0,
  request: (options = {}) => {
    // A second plus while the dialog is open re-targets the same dialog.
    pending?.reject(new CreateAgentCancelled());
    const fresh = Boolean(options.mode || options.template);
    return new Promise<SocietyAgent>((resolve, reject) => {
      pending = { resolve, reject };
      set((state) => ({
        open: true,
        initial: fresh ? (options.template ? { mode: "import", ...options } : options) : state.open ? state.initial : {},
        requestId: fresh ? state.requestId + 1 : state.requestId,
      }));
    });
  },
  finish: (agent) => {
    pending?.resolve(agent);
    pending = null;
    set({ open: false, initial: {} });
  },
  cancel: () => {
    pending?.reject(new CreateAgentCancelled());
    pending = null;
    set({ open: false, initial: {} });
  },
}));

export function isCreateCancelled(error: unknown): boolean {
  return error instanceof CreateAgentCancelled;
}
