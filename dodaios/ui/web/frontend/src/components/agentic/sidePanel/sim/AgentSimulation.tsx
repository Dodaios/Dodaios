import { Component, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useReducedMotion } from "framer-motion";
import { CanvasTexture, SRGBColorSpace, type Group, type Mesh, type MeshBasicMaterial, type PerspectiveCamera } from "three";

import { useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useThemeValue } from "@/hooks/useTheme";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import { cn } from "@/lib/utils";
import { AgentMark, agentLogoAsset } from "@/components/agentic/AgentMark";

import type { BoardActivity, BoardColumn } from "../agentBoard";
import { buildMascot, buildPlainMascot, type MascotSolid } from "./mascotGeometry";
import { mascotSpecFor } from "./mascotSpecs";
import { CAMERA_PITCH, LOOK_AT_Y, cameraDistance, layoutSimulation, phaseOf, type SimAgent, type SimField, type SimLayout, type SimSpot } from "./simLayout";

/**
 * The Agents board as a place: every coding agent is a figure on a floor.
 *
 * A figure is its agent's own mark with depth (see `mascotSpecs`), so which
 * agent is which is read from the figure itself; a name tag above it says it
 * in words. The floor has the board's four fields, and a figure stands in the
 * field its work is in and walks over when that changes. What a figure does
 * shows its state: it hops while its agent works, jumps when the agent asks
 * for the person, leans over when the agent failed, and stands still at rest.
 * A click on a figure opens its thread or terminal, as a click on its card does.
 */

const FOV = 32;
/** A figure leans back a little, so its face meets the camera that looks down on it. */
const FACE_UP = -0.3;
/** The figures are larger than life on the floor, so a mark reads from afar. */
const FIGURE_SCALE = 1.15;
/** The name tag lies on the floor in front of the figure, so it never covers a mark. */
const TAG_Z = 0.72;
/** The eyes of a mark, on either theme. */
const EYE_COLOUR = "#1b1a19";
/** A drag that ends on a figure is a turn of the view, not a click. */
const CLICK_SLOP_PX = 5;

export interface AgentSimulationProps {
  agents: SimAgent[];
  columnNames: Record<BoardColumn, string>;
  /** The agent whose thread or terminal is open. */
  selectedId: string | null;
  onOpen: (id: string) => void;
  ariaLabel: string;
  emptyText: string;
  unavailableText: string;
}

interface SimColours {
  ink: string;
  plate: string;
  fields: Record<BoardColumn, string>;
  attention: string;
  danger: string;
}

/** A CSS colour, in whatever notation the browser reports it, as `#rrggbb`. */
function toHex(colour: string, context: CanvasRenderingContext2D): string {
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = "#000";
  context.fillStyle = colour;
  context.fillRect(0, 0, 1, 1);
  const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
  return `#${[red, green, blue].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

/** The theme's colours for the scene, read from the tokens the board itself uses. */
function useSimColours(hostRef: RefObject<HTMLElement | null>): SimColours {
  const theme = useThemeValue();
  const dark = theme === "dark";
  const [tokens, setTokens] = useState({
    ink: dark ? "#ededed" : "#171717",
    plate: dark ? "#262626" : "#f0f0f0",
    accent: "#096cdc",
    success: "#15803d",
    warning: "#b45309",
    destructive: "#c52020",
  });
  useLayoutEffect(() => {
    const host = hostRef.current;
    const context = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    if (!host || !context) return;
    const probe = document.createElement("span");
    probe.style.display = "none";
    host.appendChild(probe);
    const read = (token: string) => {
      probe.style.color = `hsl(var(--${token}))`;
      return toHex(getComputedStyle(probe).color, context);
    };
    setTokens({
      ink: read("foreground"),
      plate: read("muted"),
      accent: read("accent"),
      success: read("success"),
      warning: read("warning"),
      destructive: read("destructive"),
    });
    probe.remove();
  }, [hostRef, theme]);
  return useMemo(() => ({
    ink: tokens.ink,
    plate: tokens.plate,
    fields: {
      building: tokens.accent,
      // The board's own colours for its two middle columns.
      checks: dark ? "#f778ba" : "#bf3989",
      review: dark ? "#f0883e" : "#bc4c00",
      ready: tokens.success,
    },
    attention: tokens.warning,
    danger: tokens.destructive,
  }), [tokens, dark]);
}

const PICTURE_PX = 512;
const pictures = new Map<string, CanvasTexture>();

/**
 * A mark's file as a texture, painted by the browser.
 *
 * The picture is first laid down a few pixels off in every direction, so the
 * colour runs past the outline: a figure's sides sample the very edge, and
 * would otherwise pick up the empty ground around the mark.
 */
function usePicture(url: string | null): CanvasTexture | null {
  const [picture, setPicture] = useState<CanvasTexture | null>(() => (url ? pictures.get(url) ?? null : null));
  useEffect(() => {
    if (!url) { setPicture(null); return; }
    const known = pictures.get(url);
    if (known) { setPicture(known); return; }
    let live = true;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = PICTURE_PX;
      const context = canvas.getContext("2d");
      if (!context) return;
      for (const [dx, dy] of [[-6, 0], [6, 0], [0, -6], [0, 6], [-4, -4], [4, -4], [-4, 4], [4, 4], [0, 0]]) {
        context.drawImage(image, dx, dy, PICTURE_PX, PICTURE_PX);
      }
      const texture = new CanvasTexture(canvas);
      texture.colorSpace = SRGBColorSpace;
      texture.anisotropy = 4;
      pictures.set(url, texture);
      if (live) setPicture(texture);
    };
    image.src = url;
    return () => { live = false; };
  }, [url]);
  return picture;
}

const solids = new Map<string, MascotSolid>();

/** The solid for an agent, built once per page. */
function solidFor(agent: string): MascotSolid {
  const known = solids.get(agent);
  if (known) return known;
  const spec = mascotSpecFor(agent);
  let solid: MascotSolid;
  try {
    solid = spec ? buildMascot(spec) : buildPlainMascot();
  } catch {
    solid = buildPlainMascot();
  }
  if (solid.parts.length === 0) solid = buildPlainMascot();
  solids.set(agent, solid);
  return solid;
}

/** The mark itself, as a solid. No motion of its own. */
function MascotBody({ agent, ink }: { agent: string; ink: string }) {
  const spec = mascotSpecFor(agent);
  const solid = useMemo(() => solidFor(agent), [agent]);
  const picture = usePicture(spec?.paint === "picture" ? agentLogoAsset(agent)?.url ?? null : null);
  return <>
    {solid.parts.map((part, index) => (
      <mesh key={index} geometry={part.geometry}>
        {part.eye ? <meshStandardMaterial color={EYE_COLOUR} roughness={0.35} />
          : spec?.paint === "picture" ? <meshStandardMaterial key={picture ? "picture" : "plain"} map={picture} color="#ffffff" roughness={0.5} />
          : <meshStandardMaterial color={spec?.paint === "flat" && part.fill ? part.fill : ink} roughness={0.5} />}
      </mesh>
    ))}
  </>;
}

interface FigureProps {
  agent: SimAgent;
  spot: SimSpot;
  colours: SimColours;
  still: boolean;
  selected: boolean;
  hovered: boolean;
  onHover: (id: string | null) => void;
  onOpen: (id: string) => void;
}

/** The ring under a figure says what its agent is doing, in the colours of the name tag's dot. */
function ringColourFor(activity: BoardActivity, colours: SimColours): string | null {
  if (activity === "working") return colours.fields.building;
  if (activity === "attention") return colours.attention;
  if (activity === "failed") return colours.danger;
  return null;
}

const DOT_CLASS: Record<BoardActivity, string> = {
  working: "bg-accent",
  attention: "bg-warning",
  failed: "bg-destructive",
  idle: "bg-muted-foreground/50",
};

/** One agent on the floor: its figure, its shadow, the ring of its state and its name tag. */
function Figure({ agent, spot, colours, still, selected, hovered, onHover, onOpen }: FigureProps) {
  const place = useRef<Group>(null);
  const body = useRef<Group>(null);
  const shadow = useRef<Mesh>(null);
  const ring = useRef<Mesh>(null);
  const placed = useRef(false);
  const phase = useMemo(() => phaseOf(agent.id), [agent.id]);
  const ringColour = ringColourFor(agent.activity, colours);

  useFrame(({ clock }, delta) => {
    const group = place.current;
    const figure = body.current;
    if (!group || !figure) return;
    // The first frame stands the figure on its spot; after that it walks there.
    let walking = false;
    let heading = 0;
    if (!placed.current || still) {
      group.position.set(spot.x, 0, spot.z);
      placed.current = true;
    } else {
      const dx = spot.x - group.position.x;
      const dz = spot.z - group.position.z;
      const far = Math.hypot(dx, dz);
      if (far > 0.02) {
        const step = Math.min(far, Math.max(1.2, far * 1.6) * delta);
        group.position.x += (dx / far) * step;
        group.position.z += (dz / far) * step;
        walking = far > 0.08;
        heading = Math.max(-0.7, Math.min(0.7, dx / Math.max(far, 0.001)));
      }
    }

    const t = clock.getElapsedTime() + phase * 9;
    let air = 0, yaw = 0, lean = 0, stretch = 0;
    if (still) {
      lean = agent.activity === "failed" ? 0.42 : 0;
    } else if (walking) {
      air = Math.abs(Math.sin(t * 9)) * 0.14;
      yaw = heading;
      lean = Math.sin(t * 9) * 0.07;
    } else if (agent.activity === "working") {
      const beat = Math.abs(Math.sin(t * 3.4));
      air = beat * 0.2;
      stretch = (beat - 0.5) * 0.08;
      yaw = Math.sin(t * 1.7) * 0.28;
    } else if (agent.activity === "attention") {
      const beat = (t * 0.9) % 1;
      air = beat < 0.5 ? Math.sin((beat / 0.5) * Math.PI) * 0.55 : 0;
      stretch = beat < 0.5 ? 0.06 : Math.sin(((beat - 0.5) / 0.5) * Math.PI) * -0.08;
      lean = beat >= 0.5 ? Math.sin(t * 22) * 0.04 : 0;
    } else if (agent.activity === "failed") {
      lean = 0.42;
    } else {
      stretch = Math.sin(t * 1.3) * 0.012;
      yaw = Math.sin(t * 0.45) * 0.14;
    }
    figure.position.y = air;
    figure.rotation.set(FACE_UP, yaw, lean);
    figure.scale.set(FIGURE_SCALE * (1 - stretch), FIGURE_SCALE * (1 + stretch), FIGURE_SCALE * (1 - stretch));
    if (shadow.current) {
      const spread = 1 - Math.min(0.5, air * 0.8);
      shadow.current.scale.setScalar(spread);
      (shadow.current.material as MeshBasicMaterial).opacity = 0.22 * spread;
    }
    if (ring.current) {
      if (agent.activity === "working" && !still) ring.current.rotation.z = -t * 2.4;
      if (agent.activity === "attention" && !still) ring.current.scale.setScalar(1 + Math.abs(Math.sin(t * 2.8)) * 0.16);
    }
  });

  const over = (event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); onHover(agent.id); };
  const out = () => onHover(null);
  const click = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    if (event.delta <= CLICK_SLOP_PX) onOpen(agent.id);
  };
  const wordy = hovered || selected;
  const urgent = agent.activity === "attention" || agent.activity === "failed";

  return (
    <group ref={place}>
      <mesh ref={shadow} rotation-x={-Math.PI / 2} position-y={0.036}>
        <circleGeometry args={[0.46, 28]} />
        <meshBasicMaterial color="#000000" transparent opacity={0.22} depthWrite={false} />
      </mesh>
      {ringColour && (
        <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={0.04}>
          {/* A working agent's ring is open and turns; the others are closed. */}
          <ringGeometry args={[0.6, 0.68, 48, 1, 0, agent.activity === "working" ? Math.PI * 1.5 : Math.PI * 2]} />
          <meshBasicMaterial color={ringColour} transparent opacity={0.95} depthWrite={false} />
        </mesh>
      )}
      {selected && (
        <mesh rotation-x={-Math.PI / 2} position-y={0.038}>
          <ringGeometry args={[0.74, 0.77, 48]} />
          <meshBasicMaterial color={colours.ink} transparent opacity={0.8} depthWrite={false} />
        </mesh>
      )}
      <group ref={body} scale={FIGURE_SCALE}>
        <MascotBody agent={agent.agent} ink={colours.ink} />
      </group>
      {/* The hit area: the figure's whole square, so a thin glyph is as easy to hit as a tile. */}
      <mesh position-y={0.62} onPointerOver={over} onPointerOut={out} onClick={click}>
        <boxGeometry args={[1.15, 1.24, 0.5]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      <Html center position={[0, 0.05, TAG_Z]} zIndexRange={[hovered ? 40 : 20, 0]} style={{ pointerEvents: "none" }}>
        <div data-testid="ide-sim-tag" data-item={agent.id} data-agent={agent.agent} data-activity={agent.activity}
          className={cn(
            "flex max-w-[168px] flex-col items-center whitespace-nowrap rounded border px-1 py-px text-center",
            hovered || selected ? "border-accent bg-card" : "border-border/70 bg-card/90",
          )}>
          <span className="flex items-center gap-1 text-[10.5px] font-medium leading-tight text-foreground">
            <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_CLASS[agent.activity])} />
            {agent.agentLabel}
          </span>
          {wordy && agent.title && (
            <span className="block max-w-[156px] truncate text-[10px] leading-tight text-muted-foreground">{agent.title}</span>
          )}
          {(wordy || urgent) && (
            <span className="block max-w-[156px] truncate text-[10px] font-medium leading-tight text-foreground-secondary">{agent.stateLabel}</span>
          )}
        </div>
      </Html>
    </group>
  );
}

/** One of the board's columns as a field on the floor, with its name on the front edge. */
function Field({ field, name, colour, plate }: { field: SimField; name: string; colour: string; plate: string }) {
  return (
    <group position={[field.x, 0, field.z]}>
      <mesh position-y={0}>
        <boxGeometry args={[field.width, 0.06, field.depth]} />
        <meshStandardMaterial color={plate} roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.005, field.depth / 2 + 0.05]}>
        <boxGeometry args={[field.width, 0.07, 0.1]} />
        <meshBasicMaterial color={colour} />
      </mesh>
      <Html center position={[0, 0, field.depth / 2 + 0.5]} zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
        <div data-testid={`ide-sim-field-${field.column}`} className="flex items-center gap-1.5 whitespace-nowrap text-xs font-medium">
          <span style={{ color: colour }}>{name}</span>
          <span className="tabular-nums text-muted-foreground">{field.count}</span>
        </div>
      </Html>
    </group>
  );
}

/** Keeps the whole floor in view, whatever the panel's shape. */
function Rig({ layout }: { layout: SimLayout }) {
  const camera = useThree((state) => state.camera) as PerspectiveCamera;
  const invalidate = useThree((state) => state.invalidate);
  const aspect = useThree((state) => state.size.width / Math.max(1, state.size.height));
  const distance = cameraDistance(layout, aspect, FOV);
  useLayoutEffect(() => {
    camera.position.set(0, LOOK_AT_Y + Math.sin(CAMERA_PITCH) * distance, Math.cos(CAMERA_PITCH) * distance);
    camera.lookAt(0, LOOK_AT_Y, 0);
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, distance, invalidate]);
  return <OrbitControls makeDefault target={[0, LOOK_AT_Y, 0]} enablePan={false}
    minDistance={distance * 0.3} maxDistance={distance * 1.4}
    minPolarAngle={0.3} maxPolarAngle={1.38} minAzimuthAngle={-1} maxAzimuthAngle={1} />;
}

/** The panel's shape, width over height, in coarse steps: a resize does not reshuffle the floor at every pixel. */
function useHostAspect(hostRef: RefObject<HTMLElement | null>): number {
  const [aspect, setAspect] = useState(2);
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      if (host.clientWidth > 0 && host.clientHeight > 0) {
        setAspect(Math.round((host.clientWidth / host.clientHeight) * 4) / 4);
      }
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, [hostRef]);
  return aspect;
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export default function AgentSimulation({ agents, columnNames, selectedId, onOpen, ariaLabel, emptyText, unavailableText }: AgentSimulationProps) {
  const host = useRef<HTMLDivElement>(null);
  const { generation } = useWebglSurface(host);
  const awake = useCanvasAwake(host);
  const supported = useWebglSupported();
  const still = useReducedMotion() ?? false;
  const colours = useSimColours(host);
  const [hovered, setHovered] = useState<string | null>(null);
  const aspect = useHostAspect(host);
  const layout = useMemo(() => layoutSimulation(agents, aspect), [agents, aspect]);

  // The agents on the floor, by kind: the key to which figure is which.
  const kinds = useMemo(() => {
    const seen = new Map<string, { agent: string; label: string; count: number }>();
    for (const agent of agents) {
      const key = agent.agent || agent.agentLabel;
      const entry = seen.get(key);
      if (entry) entry.count += 1;
      else seen.set(key, { agent: agent.agent, label: agent.agentLabel, count: 1 });
    }
    return [...seen.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }, [agents]);

  const unavailable = <p className="px-4 py-3 text-sm text-muted-foreground">{unavailableText}</p>;
  return (
    <div ref={host} data-testid="ide-agents-simulation" role="img" aria-label={ariaLabel}
      className={cn("relative min-h-0 flex-1 touch-none overflow-hidden", hovered && "cursor-pointer")}>
      {agents.length === 0 ? (
        <p className="px-4 py-3 text-sm text-muted-foreground">{emptyText}</p>
      ) : !supported ? unavailable : awake && (
        <SceneBoundary key={generation} fallback={unavailable}>
          <Canvas flat frameloop={still ? "demand" : "always"} dpr={[1, 2]}
            camera={{ fov: FOV, near: 0.1, far: 400, position: [0, 8, 12] }} gl={{ alpha: true, antialias: true }}>
            <ambientLight intensity={1.35} />
            <directionalLight position={[3, 7, 9]} intensity={2.3} />
            <directionalLight position={[-6, 4, 3]} intensity={0.7} />
            <Rig layout={layout} />
            {layout.fields.map((field) => (
              <Field key={field.column} field={field} name={columnNames[field.column]}
                colour={colours.fields[field.column]} plate={colours.plate} />
            ))}
            {agents.map((agent) => {
              const spot = layout.spots.get(agent.id);
              return spot ? (
                <Figure key={agent.id} agent={agent} spot={spot} colours={colours} still={still}
                  selected={selectedId === agent.id} hovered={hovered === agent.id}
                  onHover={setHovered} onOpen={onOpen} />
              ) : null;
            })}
          </Canvas>
        </SceneBoundary>
      )}
      {agents.length > 0 && (
        <ul data-testid="ide-sim-legend"
          className="pointer-events-none absolute bottom-2 left-2 z-50 flex max-w-[calc(100%-1rem)] flex-wrap gap-x-3 gap-y-1 rounded-md border border-border/60 bg-card/90 px-2 py-1 text-xs text-foreground">
          {kinds.map((kind) => (
            <li key={kind.agent || kind.label} data-agent={kind.agent} className="flex items-center gap-1.5">
              {kind.agent && <AgentMark agent={kind.agent} label={kind.label} variant="plain" size="sm" />}
              <span>{kind.label}</span>
              <span className="tabular-nums text-muted-foreground">{kind.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
