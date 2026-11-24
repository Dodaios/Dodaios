import { useCallback, useRef } from "react";

import { attachContextActions, type ContextActionProvider } from "@/lib/contextActions";

/**
 * A callback ref that gives an element its own right-click entries (see
 * `lib/contextActions.ts`). The provider is read at right-click time, so it may
 * change on every render without re-registering.
 */
export function useContextActions(
  provider: ContextActionProvider | null,
): (node: HTMLElement | null) => void {
  const providerRef = useRef(provider);
  providerRef.current = provider;
  const detach = useRef<(() => void) | null>(null);
  return useCallback((node: HTMLElement | null) => {
    detach.current?.();
    detach.current = null;
    if (node) {
      detach.current = attachContextActions(node, (target) => providerRef.current?.(target) ?? []);
    }
  }, []);
}
