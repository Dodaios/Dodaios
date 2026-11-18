/**
 * "Open nodes as they are built": whether the node window opens by itself
 * when an agent makes a node in the conversation the person is looking at
 * (components/nodes/live/autoOpen.ts).
 *
 * A per-window preference like "Autopilot toasts": it only decides what this
 * window shows, so nothing on the server needs to know. Default ON. Storage
 * failures fall back to the default.
 */
const STORAGE_KEY = "ui.nodeAutoOpen.v1";
const CHANGE_EVENT = "node-auto-open-changed";

export function isNodeAutoOpenEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setNodeAutoOpenEnabled(enabled: boolean): void {
  try {
    if (enabled) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, "off");
  } catch {
    /* storage blocked: the switch still reflects the choice for this render */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function onNodeAutoOpenChange(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  return () => window.removeEventListener(CHANGE_EVENT, listener);
}
