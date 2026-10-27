/**
 * Each game's colour and monogram for Settings → Game settings. No brand
 * marks: a hue and two letters give every game its own face while staying
 * clear of anyone's logo.
 */

const HUES: Record<string, number> = {
  fortnite: 268,
  cod_bo6: 96,
  r6_siege_x: 205,
  valorant: 354,
  cs2: 36,
  apex: 8,
  overwatch2: 26,
  battlefield6: 188,
  pubg: 46,
  marvel_rivals: 340,
  the_finals: 318,
  tarkov: 62,
  destiny2: 196,
  arc_raiders: 78,
  rocket_league: 220,
};

/** A stable hue for any game id, from the table or a hash of the id. */
export function gameHue(id: string): number {
  if (id in HUES) return HUES[id];
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
}

/** "Rainbow Six Siege X" → "RS", "Counter-Strike 2" → "CS", "Valorant" → "VA". */
export function gameMonogram(name: string): string {
  const words = name
    .replace(/[:/].*$/, "")
    .split(/[\s-]+/)
    .filter((word) => /^[A-Z0-9]/.test(word));
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length > 2 ? 1 : words.length - 1][0]).toUpperCase();
}

export function gameAccent(id: string, alpha = 1): string {
  return `hsl(${gameHue(id)} 85% 58% / ${alpha})`;
}
