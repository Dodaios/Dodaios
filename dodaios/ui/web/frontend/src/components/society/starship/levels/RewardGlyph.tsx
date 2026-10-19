/**
 * Small pictures of what a level opens: the captain's suits as tunic
 * silhouettes in their cloth and trim, decorations as their ribbon (and medal),
 * destinations as a swatch painted in the destination's own sky and planet
 * colours from `space/destinations.ts`. 48-unit grid like the insignia.
 */
import { useId } from "react";
import { slotOf, type RewardId } from "../../progression/levelCatalog";
import { destinationById, type Destination } from "../space/destinations";
import { destinationOf } from "./levelModel";

const SUITS: Record<string, { cloth: string; shade: string; trim: string; plates?: boolean; buttons?: boolean; cuffs?: boolean }> = {
  suit_field_armor: { cloth: "#566270", shade: "#3a434e", trim: "#5fd4ff", plates: true },
  suit_command_coat: { cloth: "#232a36", shade: "#161b23", trim: "#d9a441" },
  suit_dress_whites: { cloth: "#eef1f5", shade: "#c9d0d8", trim: "#d9a441", buttons: true },
  suit_admiral_coat: { cloth: "#17284a", shade: "#0f1b33", trim: "#e1b04f", cuffs: true, buttons: true },
};

const RIBBONS: Record<string, { stripes: string[]; medal?: "disc" | "star" | "cross" }> = {
  decoration_service_ribbon: { stripes: ["#1e2a3a", "#5fd4ff", "#1e2a3a", "#d9a441", "#1e2a3a"] },
  decoration_commendation: { stripes: ["#2f6b4f", "#eef1f5", "#2f6b4f"], medal: "disc" },
  decoration_star_medal: { stripes: ["#17284a", "#d9a441", "#17284a"], medal: "star" },
  decoration_legion_of_merit: { stripes: ["#8c1c3a", "#eef1f5", "#8c1c3a"], medal: "cross" },
};

function Suit({ id }: { id: string }) {
  const s = SUITS[id] ?? SUITS.suit_command_coat;
  return (
    <g>
      {/* Tunic: shoulders, sleeves, body. */}
      <path d="M13 10 L19 7 L24 12 L29 7 L35 10 L41 20 L37 23 L35 19 L35 41 L13 41 L13 19 L11 23 L7 20 Z" fill={s.cloth} stroke={s.shade} strokeWidth="1" strokeLinejoin="round" />
      <path d="M19 7 L24 17 L29 7" fill="none" stroke={s.trim} strokeWidth="1.8" strokeLinejoin="round" />
      <line x1="24" y1="17" x2="24" y2="41" stroke={s.shade} strokeWidth="1" />
      {s.plates && <><rect x="15.5" y="21" width="7" height="8" rx="1.5" fill={s.shade} /><rect x="25.5" y="21" width="7" height="8" rx="1.5" fill={s.shade} /><line x1="13" y1="33" x2="35" y2="33" stroke={s.trim} strokeWidth="1" opacity="0.8" /></>}
      {s.buttons && [22, 27, 32, 37].map((y) => <circle key={y} cx="26.6" cy={y} r="0.95" fill={s.trim} />)}
      {s.cuffs && <><path d="M7 20 L11 23" stroke={s.trim} strokeWidth="2.2" /><path d="M41 20 L37 23" stroke={s.trim} strokeWidth="2.2" /><path d="M13 10 L19 7 M35 10 L29 7" stroke={s.trim} strokeWidth="2" /></>}
    </g>
  );
}

function Decoration({ id }: { id: string }) {
  const r = RIBBONS[id] ?? RIBBONS.decoration_service_ribbon;
  const w = 26 / r.stripes.length;
  const top = r.medal ? 7 : 18;
  return (
    <g>
      {r.stripes.map((c, i) => <rect key={i} x={11 + i * w} y={top} width={w + 0.05} height="10" fill={c} />)}
      <rect x="11" y={top} width="26" height="10" rx="1" fill="none" stroke="rgba(0,0,0,0.5)" strokeWidth="0.8" />
      {r.medal && <line x1="24" y1="17" x2="24" y2="23" stroke="#c8963c" strokeWidth="1.4" />}
      {r.medal === "disc" && <circle cx="24" cy="31" r="8" fill="#e1b04f" stroke="#a8741f" strokeWidth="1.2" />}
      {r.medal === "star" && <polygon points="24,22 26.6,28.4 33.5,28.9 28.2,33.3 29.9,40 24,36.3 18.1,40 19.8,33.3 14.5,28.9 21.4,28.4" fill="#e1b04f" stroke="#a8741f" strokeWidth="1" strokeLinejoin="round" />}
      {r.medal === "cross" && <path d="M24 22 L27 28 L33 31 L27 34 L24 40 L21 34 L15 31 L21 28 Z" fill="#eef1f5" stroke="#d9a441" strokeWidth="1.4" strokeLinejoin="round" />}
    </g>
  );
}

/** The destination's sky with its planet (or singularity) as a round swatch. */
export function DestinationSwatch({ destination, size = 40 }: { destination: Destination; size?: number }) {
  const uid = useId().replace(/:/g, "");
  const { planet, sky, sun, singularity } = destination;
  const [deep, mid, bright] = planet.colours;
  return (
    <svg className="svc-glyph" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <radialGradient id={`${uid}k`} cx="0.3" cy="0.25" r="0.95">
          <stop offset="0" stopColor={sky.nebula[1]} stopOpacity={0.35 + sky.nebulaStrength * 0.5} />
          <stop offset="0.6" stopColor={sky.nebula[0]} stopOpacity={0.25 + sky.nebulaStrength * 0.55} />
          <stop offset="1" stopColor="#04060b" />
        </radialGradient>
        <radialGradient id={`${uid}p`} cx="0.35" cy="0.3" r="0.8">
          <stop offset="0" stopColor={bright} />
          <stop offset="0.45" stopColor={mid} />
          <stop offset="1" stopColor={deep} />
        </radialGradient>
        <clipPath id={`${uid}c`}><circle cx="24" cy="24" r="22" /></clipPath>
      </defs>
      <g clipPath={`url(#${uid}c)`}>
        <rect width="48" height="48" fill="#04060b" />
        <rect width="48" height="48" fill={`url(#${uid}k)`} />
        {[[9, 12], [36, 9], [40, 30], [14, 37], [28, 15], [20, 26]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i % 2 ? 0.6 : 0.9} fill="#fff" opacity="0.75" />)}
        <circle cx="35" cy="12" r={2.2 * sun.size} fill={sun.colour} opacity="0.9" />
        {sun.twin && <circle cx="40" cy="18" r="1.6" fill={sun.colour} opacity="0.8" />}
        {singularity && (
          <g>
            <ellipse cx="24" cy="27" rx="15" ry="3.4" fill="none" stroke={sun.colour} strokeWidth="1.6" opacity="0.85" />
            <circle cx="24" cy="27" r="7" fill="#000" stroke={sun.colour} strokeOpacity="0.5" strokeWidth="0.8" />
          </g>
        )}
        {planet.kind !== "none" && (
          <g>
            <circle cx="20" cy="44" r="21" fill={`url(#${uid}p)`} />
            <circle cx="20" cy="44" r="21" fill="none" stroke={planet.atmosphere} strokeOpacity="0.6" strokeWidth="1.4" />
            {planet.rings && <ellipse cx="20" cy="40" rx="27" ry="4" fill="none" stroke={planet.rings.colour} strokeOpacity="0.75" strokeWidth="1.3" />}
          </g>
        )}
      </g>
      <circle cx="24" cy="24" r="22" fill="none" stroke="rgba(255,255,255,0.14)" />
    </svg>
  );
}

/** The picture of any reward; `home` paints the ship's home orbit. */
export function RewardGlyph({ reward, size = 40 }: { reward: RewardId | "home"; size?: number }) {
  if (reward === "home") return <DestinationSwatch destination={destinationById("home")} size={size} />;
  const destination = destinationOf(reward);
  if (destination) return <DestinationSwatch destination={destination} size={size} />;
  return (
    <svg className="svc-glyph" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      {slotOf(reward) === "suit" ? <Suit id={reward} /> : <Decoration id={reward} />}
    </svg>
  );
}

/** "Own clothes" / "Automatic" in the suit choice: a plain or a starred tunic outline. */
export function SuitOutline({ starred, size = 40 }: { starred: boolean; size?: number }) {
  return (
    <svg className="svc-glyph" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path d="M13 10 L19 7 L24 12 L29 7 L35 10 L41 20 L37 23 L35 19 L35 41 L13 41 L13 19 L11 23 L7 20 Z" fill="none" stroke="#5c6878" strokeWidth="1.4" strokeLinejoin="round" />
      {starred && <polygon points="24,20 25.8,24.4 30.5,24.7 26.9,27.7 28,32.3 24,29.8 20,32.3 21.1,27.7 17.5,24.7 22.2,24.4" fill="#d9a441" />}
    </svg>
  );
}
