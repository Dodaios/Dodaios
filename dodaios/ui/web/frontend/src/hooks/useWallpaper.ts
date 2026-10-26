import { useEffect } from "react";
import { create } from "zustand";

/**
 * The picture behind the tiling layout.
 *
 * The backend serves the user's desktop wallpaper by default, or the custom
 * picture uploaded in the layout menu (`/api/wallpaper`). `url` is null while
 * unknown or when the system has no wallpaper to give; the stage then paints
 * its plain fallback ground.
 */
export type WallpaperSource = "custom" | "desktop" | "none";

interface WallpaperState {
  source: WallpaperSource | null;
  url: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  upload: (file: File) => Promise<boolean>;
  reset: () => Promise<boolean>;
}

type Info = { source?: WallpaperSource; version?: string };

function fromInfo(info: Info): Pick<WallpaperState, "source" | "url"> {
  const source = info.source ?? "none";
  return {
    source,
    url: source === "none" ? null : `/api/wallpaper?v=${encodeURIComponent(info.version ?? "")}`,
  };
}

export const useWallpaperStore = create<WallpaperState>((set, get) => ({
  source: null,
  url: null,
  loading: false,
  refresh: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const response = await fetch("/api/wallpaper/info");
      if (response.ok) set(fromInfo((await response.json()) as Info));
    } catch {
      /* backend unreachable: keep what is shown */
    } finally {
      set({ loading: false });
    }
  },
  upload: async (file) => {
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/api/wallpaper", { method: "POST", body });
      if (!response.ok) return false;
      set(fromInfo((await response.json()) as Info));
      return true;
    } catch {
      return false;
    }
  },
  reset: async () => {
    try {
      const response = await fetch("/api/wallpaper", { method: "DELETE" });
      if (!response.ok) return false;
      set(fromInfo((await response.json()) as Info));
      return true;
    } catch {
      return false;
    }
  },
}));

/** The wallpaper URL; asks the backend once per mount and on window focus. */
export function useWallpaper(enabled: boolean): string | null {
  const url = useWallpaperStore((s) => s.url);
  useEffect(() => {
    if (!enabled) return;
    void useWallpaperStore.getState().refresh();
    // A wallpaper changed in the OS shows up the next time the app is focused.
    const onFocus = () => void useWallpaperStore.getState().refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled]);
  return url;
}
