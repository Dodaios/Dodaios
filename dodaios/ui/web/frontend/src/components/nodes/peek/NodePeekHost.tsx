/**
 * Where the node window is drawn: once, at the app's root.
 *
 * Nothing but a subscription while no node is open; the window (and with it
 * the stage and the editors) is its own chunk, loaded on the first click on
 * a page card.
 *
 * The window belongs to the page it was opened on. A change of section (a
 * spoken "go to settings", a link in the conversation, "Open in Nodes")
 * closes it, so it never hangs over a page it has nothing to do with.
 */
import { Suspense, lazy, useEffect } from "react";

import { useEventStore } from "@/store/events";
import { useNodePeek } from "@/store/nodePeek";

const NodePeekWindow = lazy(() => import("./NodePeekWindow"));

export function NodePeekHost() {
  const peek = useNodePeek((s) => s.peek);
  useEffect(
    () =>
      useEventStore.subscribe((state, previous) => {
        if (state.activeSection !== previous.activeSection) useNodePeek.getState().close();
      }),
    [],
  );
  if (peek === null) return null;
  return (
    <Suspense
      // The scrim is there at the click; the window follows with its chunk.
      fallback={<div className="fixed inset-0 z-[60] bg-scrim/55 backdrop-blur-[2px]" data-testid="node-peek-loading" />}
    >
      <NodePeekWindow peek={peek} />
    </Suspense>
  );
}
