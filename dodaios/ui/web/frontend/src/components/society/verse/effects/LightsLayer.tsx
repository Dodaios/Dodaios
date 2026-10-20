/**
 * The deck's lamps, alive. The photograph has every fixture lit; this layer
 * only adds what a still image cannot, through sprites at the light sockets
 * (props from the cook: `colour`, `blink_hz`, `pulse_hz`, `light_kind`):
 *
 * - blinking lamps (beacons, lift calls) go dark and bright at their rate;
 * - alarm lamps blink only while someone on this deck has a fault;
 * - a pulsing source (the reactor core) breathes very slowly;
 * - now and then one ceiling fixture or steady lamp dips for a moment. A
 *   ceiling is not in the photograph, so its dip darkens the pool of light it
 *   throws on the floor below.
 *
 * Everything stays faint: these are the room's own lights, not effects.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { AdditiveBlending, CanvasTexture, Group, NormalBlending, Sprite, SpriteMaterial, type Blending, type Texture } from "three";
import type { Deck, Socket } from "../content/deck";
import { RENDER_ORDER } from "../engine/renderOrder";
import { hash32 } from "../life/crew";
import { insidePolygon } from "../actors/roomLight";

function glowTexture(): Texture {
  const s = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = s;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.5)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  return new CanvasTexture(canvas);
}

export type LampKind = "blink" | "alarm" | "pulse" | "steady" | "ceiling";

interface Lamp { socket: Socket; kind: LampKind; hz: number; glow: Sprite; shade: Sprite }

/** Seconds between two dips somewhere on the deck. */
const FLICKER_EVERY_S = 24;

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

/** What a light socket does, from its id and the cook's props. Pure. */
export function lampKind(socket: Pick<Socket, "id" | "props">): LampKind {
  if (socket.id.includes("alarm")) return "alarm";
  if (num(socket.props.blink_hz) > 0) return "blink";
  if (num(socket.props.pulse_hz) > 0) return "pulse";
  if (String(socket.props.light_kind ?? "").startsWith("ceiling")) return "ceiling";
  return "steady";
}

/** A floor point under a ceiling fixture of the room the socket lights, chosen by `seed`. Pure. */
export function ceilingPool(deck: Pick<Deck, "rooms">, socket: Socket, seed: number): { x: number; y: number; z: number } {
  const room = deck.rooms.find((r) => r.id === socket.room) ?? deck.rooms.find((r) => insidePolygon(socket.x, socket.z, r.polygon));
  if (!room) return { x: socket.x, y: 0, z: socket.z };
  const xs = room.polygon.map((p) => p[0]);
  const zs = room.polygon.map((p) => p[1]);
  const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
  // Fixtures hang on the 1.2 m grid; try a few seeded grid points until one is inside the room.
  for (let k = 0; k < 8; k++) {
    const h = hash32(`${seed}:${k}`);
    const x = x0 + 0.6 + Math.floor(((h & 0xffff) / 0xffff) * Math.max(1, (x1 - x0) / 1.2)) * 1.2;
    const z = z0 + 0.6 + Math.floor(((h >>> 16) / 0xffff) * Math.max(1, (z1 - z0) / 1.2)) * 1.2;
    if (insidePolygon(x, z, room.polygon)) return { x, y: room.floorY, z };
  }
  return { x: (x0 + x1) / 2, y: room.floorY, z: (z0 + z1) / 2 };
}

export function LightsLayer({ deck, alarm, reduced }: { deck: Deck; alarm: boolean; reduced: boolean }) {
  const scene = useThree((s) => s.scene);
  const texture = useMemo(glowTexture, []);
  const alarmRef = useRef(alarm);
  alarmRef.current = alarm;

  const lamps = useMemo<Lamp[]>(() => deck.sockets.filter((s) => s.kind === "light").map((socket) => {
    const kind = lampKind(socket);
    const colour = typeof socket.props.colour === "string" ? socket.props.colour : kind === "alarm" ? "#ff3a2a" : "#f4f7ff";
    const sprite = (blending: Blending, tint: string) => {
      const s = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthWrite: false, toneMapped: false, blending, color: tint, opacity: 0 }));
      s.position.set(socket.x, socket.y, socket.z);
      s.renderOrder = RENDER_ORDER.flicker;
      return s;
    };
    const glow = sprite(AdditiveBlending, colour);
    const shade = sprite(NormalBlending, "#000000");
    const radius = num(socket.props.radius);
    glow.scale.setScalar(kind === "pulse" ? Math.min(8, Math.max(2, radius * 0.4)) : 0.6);
    shade.scale.setScalar(kind === "ceiling" ? 2.6 : kind === "steady" ? 1.0 : 0.32);
    return { socket, kind, hz: num(socket.props.blink_hz) || num(socket.props.pulse_hz) || 0.8, glow, shade };
  }), [deck, texture]);

  const group = useMemo(() => new Group(), []);
  useEffect(() => {
    for (const l of lamps) group.add(l.glow, l.shade);
    scene.add(group);
    return () => {
      scene.remove(group);
      for (const l of lamps) {
        group.remove(l.glow, l.shade);
        l.glow.material.dispose();
        l.shade.material.dispose();
      }
    };
  }, [lamps, group, scene]);
  useEffect(() => () => texture.dispose(), [texture]);

  const dippers = useMemo(() => lamps.filter((l) => l.kind === "ceiling" || l.kind === "steady"), [lamps]);
  // The window's dip (which lamp, when, whether its floor pool is placed), worked out once per window.
  const dip = useRef<{ dippers: readonly Lamp[]; window: number; pick: Lamp | null; at: number; placed: boolean }>({
    dippers: [], window: -1, pick: null, at: 0, placed: false,
  });

  useFrame(() => {
    const t = performance.now() / 1000;
    const window = Math.floor(t / FLICKER_EVERY_S);
    const d = dip.current;
    if (d.window !== window || d.dippers !== dippers) {
      d.dippers = dippers;
      d.window = window;
      d.pick = dippers.length ? dippers[hash32(`w${window}`) % dippers.length] : null;
      d.at = window * FLICKER_EVERY_S + ((hash32(`t${window}`) % 1000) / 1000) * (FLICKER_EVERY_S - 2);
      d.placed = false;
    }
    const pick = reduced ? null : d.pick;
    const at = d.at;
    for (const l of lamps) {
      const g = l.glow.material;
      const s = l.shade.material;
      switch (l.kind) {
        case "blink":
        case "alarm": {
          const on = l.kind === "blink" || alarmRef.current;
          if (!on) { g.opacity = 0; s.opacity = 0; break; }
          if (reduced) { g.opacity = 0.3; s.opacity = 0; break; }
          // Lit for the first half of each cycle; dark (the baked glow covered) for the second.
          const lit = (t * l.hz) % 1 < 0.5;
          g.opacity = lit ? 0.35 : 0;
          s.opacity = lit ? 0 : 0.55;
          break;
        }
        case "pulse":
          g.opacity = reduced ? 0.06 : 0.04 + 0.04 * (0.5 + 0.5 * Math.sin(t * Math.PI * 2 * l.hz));
          break;
        default: {
          g.opacity = 0;
          if (l !== pick) { s.opacity = 0; break; }
          const dt = t - at;
          if (l.kind === "ceiling" && dt < 0 && !d.placed) {
            const p = ceilingPool(deck, l.socket, window);
            l.shade.position.set(p.x, p.y + 0.02, p.z);
            d.placed = true;
          }
          // Two quick dips, about a third of a second in all.
          s.opacity = dt > 0 && dt < 0.36 ? (dt < 0.08 || (dt > 0.18 && dt < 0.26) ? 0.16 : 0.05) : 0;
        }
      }
    }
  });

  return null;
}
