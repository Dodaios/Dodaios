import { useEffect, useState } from "react";

/**
 * The `verse.unreal_preview` config flag: the side panel shows the Unreal stream only while it
 * is on, until the deletion PR removes the three.js Verse. The last answer is remembered, so the
 * tab picks the right view on the first paint of the next visit.
 */
const STORAGE_KEY = "dodaios.verse.unrealPreview.v1";
let pending: Promise<boolean> | null = null;

function remembered(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function remember(value: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    /* private mode */
  }
}

export function readUnrealPreview(config: unknown): boolean {
  if (!config || typeof config !== "object") return false;
  const verse = (config as { verse?: unknown }).verse;
  return Boolean(verse && typeof verse === "object" && (verse as { unreal_preview?: unknown }).unreal_preview === true);
}

async function fetchFlag(): Promise<boolean> {
  try {
    const res = await fetch("/api/config", { cache: "no-store", credentials: "same-origin" });
    if (!res.ok) return false;
    return readUnrealPreview(await res.json());
  } catch {
    return false;
  }
}

/** Test hook: forget the cached answer. */
export function resetUnrealPreviewFlag(): void {
  pending = null;
}

export function useUnrealPreviewFlag(): boolean {
  const [enabled, setEnabled] = useState(remembered);
  useEffect(() => {
    let live = true;
    pending ??= fetchFlag();
    void pending.then((value) => {
      remember(value);
      if (live) setEnabled(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return enabled;
}
