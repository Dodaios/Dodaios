/**
 * The character library, loaded once per session and shared by every stage.
 * Without it the decks still show (people simply are not there yet); a failed
 * load is logged and tried again on the next mount.
 */
import { useEffect, useState } from "react";
import { CharacterLibrary } from "./characters";

let pending: Promise<CharacterLibrary> | null = null;

export function useCharacterLibrary(enabled: boolean): CharacterLibrary | null {
  const [library, setLibrary] = useState<CharacterLibrary | null>(null);
  useEffect(() => {
    if (!enabled || library) return;
    let alive = true;
    if (!pending) {
      pending = CharacterLibrary.load(new AbortController().signal);
      pending.catch((error: unknown) => {
        console.warn("Verse characters unavailable", error);
        pending = null;
      });
    }
    pending.then((lib) => { if (alive) setLibrary(lib); }, () => undefined);
    return () => { alive = false; };
  }, [enabled, library]);
  return library;
}
