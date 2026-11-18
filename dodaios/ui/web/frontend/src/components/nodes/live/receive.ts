/**
 * A `NodeChanged` event from the WebSocket, put to use (`hooks/useWebSocket`).
 *
 * The live store hears it, and every open view of the node hears it now
 * instead of on its next poll: the stage's watcher (`NodeUpkeepBar`) gets the
 * new update time, which reloads the page or hands the revision to the open
 * editor, and the library's cards follow.
 */
import type { QueryClient } from "@tanstack/react-query";

import { invalidateNodes, type NodeState } from "../useNodes";
import { parseNodeChange, useNodeLive, type NodeChange } from "./liveStore";

/** The library re-reads at most this often while an agent writes. */
const LIBRARY_EVERY_MS = 1_500;
let libraryTimer: number | null = null;

function refreshLibrary(client: QueryClient, now: boolean): void {
  if (now) {
    if (libraryTimer !== null) window.clearTimeout(libraryTimer);
    libraryTimer = null;
    invalidateNodes(client);
    return;
  }
  if (libraryTimer !== null) return;
  libraryTimer = window.setTimeout(() => {
    libraryTimer = null;
    invalidateNodes(client);
  }, LIBRARY_EVERY_MS);
}

/** Tell the node's watcher what changed, so an open page or editor follows at once. */
function tellWatcher(client: QueryClient, change: NodeChange): void {
  const key = ["node-upkeep", change.slug];
  const known = client.getQueryData<NodeState>(key);
  if (known) {
    if (known.updated_at >= change.updatedAt) return;
    client.setQueryData<NodeState>(key, {
      ...known,
      version: change.version,
      updated_at: change.updatedAt,
      title: change.title || known.title,
    });
  } else {
    void client.invalidateQueries({ queryKey: key });
  }
}

export function receiveNodeChange(payload: unknown, client: QueryClient): NodeChange | null {
  const change = parseNodeChange(payload);
  if (change === null) return null;
  useNodeLive.getState().receive(change);
  tellWatcher(client, change);
  refreshLibrary(client, change.action === "create");
  return change;
}
