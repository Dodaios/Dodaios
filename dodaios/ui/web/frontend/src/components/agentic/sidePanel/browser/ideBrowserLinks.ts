/**
 * Links clicked inside the Agentic IDE open in its own Browser tab.
 *
 * On the Windows desktop app the Browser tab shows a real window of the
 * user's Chrome. Handing a link to the system default browser there sent it
 * to that same Chrome, which opened it in its last active window: often the
 * panel's window while it was hidden behind another tab, so the click only
 * made the screen flicker. Inside the IDE a link therefore brings the
 * Browser tab forward and opens there as a new tab. Everywhere else (a
 * browser tab, the built-in page view) it still goes to the user's browser.
 */
import { create } from "zustand";

import { hasEmbeddedDesktopBridge } from "@/lib/embeddedDesktop";
import { openExternalUrl } from "@/lib/openExternal";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

const BUILTIN_KEY = "jarvis.agenticIde.browserBuiltin.v1";

/** Whether the reader picked the built-in page view over their own browser. */
export function storedBuiltin(): boolean {
  try {
    return localStorage.getItem(BUILTIN_KEY) === "1";
  } catch {
    return false;
  }
}

export function persistBuiltin(value: boolean): void {
  try {
    if (value) localStorage.setItem(BUILTIN_KEY, "1");
    else localStorage.removeItem(BUILTIN_KEY);
  } catch {
    /* a convenience only */
  }
}

export interface IdeBrowserLink {
  id: number;
  url: string;
}

interface IdeBrowserLinkState {
  /** The newest link waiting for the Browser tab; a newer click replaces it. */
  pending: IdeBrowserLink | null;
  request: (url: string) => void;
  /** The Browser tab took the link with this id. */
  take: (id: number) => void;
}

let nextId = 1;

export const useIdeBrowserLinkStore = create<IdeBrowserLinkState>((set, get) => ({
  pending: null,
  request: (url) => set({ pending: { id: nextId++, url } }),
  take: (id) => {
    if (get().pending?.id === id) set({ pending: null });
  },
}));

function isWebAddress(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && !!parsed.host;
  } catch {
    return false;
  }
}

/**
 * Open `url` from a surface of the IDE. Resolves true when it was handed on.
 * On the desktop app with the reader's own browser in the panel, the Browser
 * tab comes forward and opens the address; otherwise the user's browser does.
 */
export async function openLinkInIdeBrowser(url: string): Promise<boolean> {
  if (!url) return false;
  if (!hasEmbeddedDesktopBridge() || storedBuiltin() || !isWebAddress(url)) {
    return openExternalUrl(url);
  }
  useIdeBrowserLinkStore.getState().request(url);
  useIdeSidePanelStore.getState().openTab("browser");
  return true;
}
