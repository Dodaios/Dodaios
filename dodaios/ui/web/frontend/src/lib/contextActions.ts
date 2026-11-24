/**
 * Area-specific entries for the app-wide right-click menu.
 *
 * The menu in `components/EditContextMenu.tsx` knows only Cut / Copy / Paste /
 * Select all, the same four entries everywhere. A part of the UI that has
 * something of its own to offer (a terminal can be cleared, a link opened)
 * registers a provider on its root element. On a right-click the menu walks up
 * from the clicked element and shows every provider's entries above the edit
 * entries, the innermost area first.
 *
 * Kept free of React, like `editActions.ts`, so a non-React surface (an xterm
 * container) can register entries too.
 */

import type { LucideIcon } from "lucide-react";

export interface ContextAction {
  /** Stable key, unique within one provider. */
  id: string;
  label: string;
  icon?: LucideIcon;
  /** Shown right-aligned, e.g. "Ctrl+L". Display only. */
  shortcut?: string;
  disabled?: boolean;
  run: () => void | Promise<void>;
}

/** Called at right-click time with the element that was clicked. */
export type ContextActionProvider = (target: Element) => ContextAction[];

const PROVIDER_KEY = "__dodaiosContextActions";
const PROVIDER_SELECTOR = "[data-context-actions]";

/** Register entries for `element` and everything inside it. Returns a cleanup. */
export function attachContextActions(
  element: HTMLElement,
  provider: ContextActionProvider,
): () => void {
  element.setAttribute("data-context-actions", "");
  const host = element as unknown as Record<string, unknown>;
  host[PROVIDER_KEY] = provider;
  return () => {
    if (host[PROVIDER_KEY] !== provider) return;
    delete host[PROVIDER_KEY];
    element.removeAttribute("data-context-actions");
  };
}

/**
 * Entries for a right-click on `target`, one group per registered area,
 * innermost first. Groups without entries are left out.
 */
export function collectContextActions(target: Element | null): ContextAction[][] {
  const groups: ContextAction[][] = [];
  let node = target?.closest?.(PROVIDER_SELECTOR) ?? null;
  while (node) {
    const provider = (node as unknown as Record<string, unknown>)[PROVIDER_KEY] as
      | ContextActionProvider
      | undefined;
    if (provider) {
      const actions = provider(target as Element);
      if (actions.length > 0) groups.push(actions);
    }
    node = node.parentElement?.closest(PROVIDER_SELECTOR) ?? null;
  }
  return groups;
}

/** The link under a right-click, if it points somewhere a browser can open. */
export function linkUnder(target: Element | null): string | null {
  const anchor = target?.closest?.<HTMLAnchorElement>("a[href]") ?? null;
  if (!anchor) return null;
  const href = anchor.href;
  return /^(https?:|mailto:)/i.test(href) ? href : null;
}
