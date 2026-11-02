/**
 * Where the Unreal Verse launcher card sits on the Verse view: the bottom-right
 * corner, only while the `verse.unreal_preview` flag is on (`GET /api/verse/flags`).
 * Renders nothing otherwise, so the three.js Verse is untouched until parity.
 */
import { useEffect, useState } from "react";
import { VerseLauncherCard } from "./VerseLauncherCard";
import { fetchVerseFlags } from "./verseHostApi";

export function VerseHostMount() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let alive = true;
    fetchVerseFlags().then(
      (flags) => { if (alive) setOn(flags.unreal_preview); },
      () => { if (alive) setOn(false); },
    );
    return () => { alive = false; };
  }, []);
  if (!on) return null;
  return (
    <div className="pointer-events-none absolute bottom-6 right-4 z-30 flex justify-end">
      <div className="pointer-events-auto"><VerseLauncherCard /></div>
    </div>
  );
}
