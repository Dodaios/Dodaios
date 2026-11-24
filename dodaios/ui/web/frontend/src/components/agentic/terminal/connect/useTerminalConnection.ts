import { useEffect, type MutableRefObject } from "react";
import { mountTerminal } from "./mountTerminal";
import { installPaneOutput } from "./installPaneOutput";
import { installPaneSizing } from "./installPaneSizing";
import { installPaneSocket } from "./installPaneSocket";
import { installPaneObservers } from "./installPaneObservers";
import { teardownPane } from "./teardownPane";
import type { PanePorts, PaneState } from "./paneRuntime";

export type TerminalConnectionArgs = Omit<PanePorts, "container"> & {
  containerRef: MutableRefObject<HTMLDivElement | null>;
  restartToken: number;
  geometryReady: boolean;
  fontReady: boolean;
};

/**
 * Build the xterm, open the pane's socket and keep both wired until the pane's
 * identity changes. One effect, in the order the pane has always run it: the
 * segments are called in sequence and torn down by `teardownPane`.
 */
export function useTerminalConnection(args: TerminalConnectionArgs) {
  const { containerRef, restartToken, geometryReady, fontReady, ...ports } = args;
  const { name, workspaceId } = ports;
  useEffect(() => {
    if (!geometryReady || !fontReady) return;
    const container = containerRef.current;
    if (!container) return;
    const p: PanePorts = { ...ports, container };
    const s = {} as PaneState;
    const mounted = mountTerminal(p, s);
    const output = installPaneOutput(p, s, mounted);
    const sizing = installPaneSizing(p, s, { ...mounted, ...output });
    installPaneSocket(p, s, { ...mounted, ...output, ...sizing });
    const observers = installPaneObservers(p, s, { ...mounted, ...output, ...sizing });
    return () =>
      teardownPane(p, s, { ...mounted, ...output, ...sizing, ...observers });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see the header of
    // ../../AgenticTerminal: appearance/fontSize must NOT rebuild the pane (it
    // would kill the agent).
  }, [name, workspaceId, restartToken, geometryReady, fontReady]);
}
