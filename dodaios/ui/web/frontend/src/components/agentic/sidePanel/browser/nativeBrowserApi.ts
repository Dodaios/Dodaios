/**
 * Talks to `/api/ide-browser/*`: the user's own browser shown inside the panel.
 *
 * On the Windows desktop app the panel shows a real window of the user's
 * Chrome (or Edge, Brave), opened with their profile, so every site works and
 * every sign-in is there. The backend opens the window and keeps it on the
 * panel's rectangle; see `dodaios/ui/browser_embed.py`.
 */
import { useQuery } from "@tanstack/react-query";

import { windowIdentity } from "@/lib/sectionWindows";
import { useEventStore } from "@/store/events";

export interface NativeBrowserProfile {
  directory: string;
  name: string;
  email: string;
}

export interface NativeBrowser {
  id: string;
  label: string;
  profiles: NativeBrowserProfile[];
  last_used: string | null;
}

/** `released`: handed back as a normal window ("open in its own window"). */
export type NativeBrowserState = "idle" | "launching" | "embedded" | "closed" | "released" | "error";

export interface NativeBrowserStatus {
  ok?: boolean;
  available: boolean;
  reason: string;
  state: NativeBrowserState;
  browser?: string;
  profile?: string;
  visible?: boolean;
  browsers: NativeBrowser[];
}

export interface NativeBrowserChoice {
  browser: string;
  profile: string;
}

export const NATIVE_BROWSER_STATUS_QUERY = ["ide-browser", "status"] as const;

const UNAVAILABLE: NativeBrowserStatus = {
  available: false, reason: "request_failed", state: "idle", browsers: [],
};

async function call(path: string, body?: unknown): Promise<NativeBrowserStatus> {
  try {
    const response = await fetch(`/api/ide-browser/${path}`, body === undefined ? undefined : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      // A hide sent while the page unloads must still arrive.
      keepalive: true,
    });
    if (!response.ok) return UNAVAILABLE;
    return { browsers: [], reason: "", ...(await response.json()) } as NativeBrowserStatus;
  } catch {
    return UNAVAILABLE;
  }
}

/** The window this page is shown in: a detached view's id, or null for the main window. */
export function currentWindowView(): string | null {
  const { solo, activeSection } = useEventStore.getState();
  return solo ? windowIdentity(window.location.search, activeSection) : null;
}

export function useNativeBrowserStatus(enabled: boolean, poll: boolean) {
  return useQuery({
    queryKey: NATIVE_BROWSER_STATUS_QUERY,
    queryFn: () => call("status"),
    enabled,
    // The user can close the window or switch tabs in it at any time.
    refetchInterval: poll ? 1500 : false,
    staleTime: 1000,
  });
}

export function launchNativeBrowser(choice: NativeBrowserChoice, url: string | null) {
  return call("launch", { ...choice, url, view: currentWindowView() });
}

export interface PanelPlacement {
  owner: string;
  visible: boolean;
  rect: { x: number; y: number; width: number; height: number } | null;
  dpr: number;
}

export function placeNativeBrowser(placement: PanelPlacement) {
  return call("place", { ...placement, view: currentWindowView() });
}

export function releaseNativeBrowser(close: boolean) {
  return call("release", { close });
}

const CHOICE_KEY = "jarvis.agenticIde.browserProfile.v1";

/** The browser and profile picked last, if it still exists; else the browser's own last profile. */
export function initialChoice(browsers: NativeBrowser[]): NativeBrowserChoice | null {
  let stored: NativeBrowserChoice | null = null;
  try {
    stored = JSON.parse(localStorage.getItem(CHOICE_KEY) ?? "null") as NativeBrowserChoice | null;
  } catch {
    stored = null;
  }
  if (stored) {
    const browser = browsers.find((b) => b.id === stored?.browser);
    if (browser?.profiles.some((p) => p.directory === stored?.profile)) return stored;
  }
  const first = browsers[0];
  if (!first) return null;
  const profile = first.last_used ?? first.profiles[0]?.directory;
  return profile ? { browser: first.id, profile } : null;
}

export function rememberChoice(choice: NativeBrowserChoice): void {
  try {
    localStorage.setItem(CHOICE_KEY, JSON.stringify(choice));
  } catch {
    /* a convenience only */
  }
}
