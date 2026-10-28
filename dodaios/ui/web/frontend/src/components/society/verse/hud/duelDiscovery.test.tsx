/**
 * The duel can be found: the lift names the arena on deck 3, the tool rail's
 * Duel button says where it is, the help mentions it, and the deck shows a
 * "Duel · E" marker near the reactor ring and an icon over it from above.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import de from "@/i18n/locales/ship/verse.de.json";
import en from "@/i18n/locales/ship/verse.en.json";
import es from "@/i18n/locales/ship/verse.es.json";
import pt from "@/i18n/locales/ship/verse.pt.json";
import zh from "@/i18n/locales/ship/verse.zh.json";
import { REACTOR_ARENA } from "../combat/arenaReactor";
import type { StageRuntime } from "../runtime";
import { Toolbar } from "./DeckBar";
import { FloatingLabels } from "./FloatingLabels";
import { DUEL_BEACON_RANGE_M, duelBeacon, ringRadius } from "./duelBeacon";

const t = (key: string) => key;
const C = REACTOR_ARENA.centre;

afterEach(cleanup);

describe("duel beacon", () => {
  it("shows an icon over the shaft in the bird's-eye view, wherever the commander is", () => {
    expect(duelBeacon(REACTOR_ARENA, 0, "overview", null)).toEqual({ kind: "icon", x: C.x, y: 0, z: C.z });
    expect(duelBeacon(REACTOR_ARENA, 0, "overview", { x: 0, z: 0 })?.kind).toBe("icon");
  });

  it("shows a marker over the nearest ring console only near the ring", () => {
    const edge = ringRadius(REACTOR_ARENA) + DUEL_BEACON_RANGE_M;
    expect(duelBeacon(REACTOR_ARENA, 0, "follow", { x: C.x, z: C.z + edge + 0.5 })).toBeNull();
    expect(duelBeacon(REACTOR_ARENA, 0, "follow", null)).toBeNull();
    const near = duelBeacon(REACTOR_ARENA, 2, "follow", { x: C.x + 3, z: C.z + edge - 0.5 });
    expect(near?.kind).toBe("label");
    // South-east of the axis: the ring_4 console (x > centre, z > centre), lifted above the floor.
    const ring4 = REACTOR_ARENA.terminals.find((tm) => tm.id.endsWith("_4"))!;
    expect(near).toMatchObject({ x: ring4.x, z: ring4.z });
    expect(near!.y).toBeGreaterThan(2);
  });
});

function fakeRuntime(mode: "follow" | "overview", at: { x: number; z: number }) {
  const afterFrame = new Set<() => void>();
  const runtime = {
    poses: new Map([["commander", { id: "commander", x: at.x, y: 0, z: at.z, yaw: 0, height: 1.8, moving: false }]]),
    afterFrame,
    control: { mode },
    eye: null,
    view: { vp: { width: 800, height: 600 } },
    toScreen: (_x: number, _y: number, _z: number, out: { x: number; y: number }) => { out.x = 120; out.y = 80; return out; },
    inSight: () => true,
  } as unknown as StageRuntime;
  return { runtime, frame: () => afterFrame.forEach((f) => f()) };
}

describe("duel marker on the deck", () => {
  const spot = { arena: REACTOR_ARENA, floorY: 0, commanderId: "commander", label: "verse.duel.marker" };

  it("puts the marker over the console near the reactor and keeps the icon away", () => {
    const { runtime, frame } = fakeRuntime("follow", { x: C.x, z: C.z + 10 });
    render(<FloatingLabels runtime={runtime} plates={[]} station={null} deck={null} duel={spot} />);
    frame();
    const marker = screen.getByTestId("verse-duel-marker");
    expect(marker.textContent).toBe("verse.duel.markerE");
    expect(marker.style.transform).toBe("translate(120px, 80px)");
    expect(screen.getByTestId("verse-duel-icon").style.transform).toBe("translate(-9999px, -9999px)");
  });

  it("hides the marker far from the reactor", () => {
    const { runtime, frame } = fakeRuntime("follow", { x: C.x, z: C.z + 40 });
    render(<FloatingLabels runtime={runtime} plates={[]} station={null} deck={null} duel={spot} />);
    frame();
    expect(screen.getByTestId("verse-duel-marker").style.transform).toBe("translate(-9999px, -9999px)");
  });

  it("shows the icon from above", () => {
    const { runtime, frame } = fakeRuntime("overview", { x: 0, z: 0 });
    render(<FloatingLabels runtime={runtime} plates={[]} station={null} deck={null} duel={spot} />);
    frame();
    expect(screen.getByTestId("verse-duel-icon").style.transform).toBe("translate(120px, 80px)");
    expect(screen.getByTestId("verse-duel-marker").style.transform).toBe("translate(-9999px, -9999px)");
  });

  it("renders nothing for the duel off the arena deck", () => {
    const { runtime } = fakeRuntime("follow", { x: C.x, z: C.z });
    render(<FloatingLabels runtime={runtime} plates={[]} station={null} deck={null} />);
    expect(screen.queryByTestId("verse-duel-marker")).toBeNull();
    expect(screen.queryByTestId("verse-duel-icon")).toBeNull();
  });
});

describe("duel button on the tool rail", () => {
  it("is labelled Duel and says where the arena is", () => {
    render(<Toolbar t={t} view="third" firstAvailable onView={() => {}} onLift={() => {}} onCommander={() => {}} onDuel={() => {}} onHelp={() => {}} />);
    const button = screen.getByRole("button", { name: /verse\.tools\.duel/ });
    expect(button.textContent).toContain("verse.tools.duel");
    expect(button.getAttribute("title")).toBe("verse.tools.duel_hint");
  });
});

describe("duel strings", () => {
  const locales = { de, en, es, pt, zh } as const;
  it.each(Object.entries(locales))("%s names the arena in the lift, the button, the marker and the help", (_, file) => {
    const v = file.verse as unknown as Record<string, Record<string, string>>;
    expect(v.deck.engineering_about).toContain(" · ");
    for (const s of [v.tools.duel_hint, v.duel.marker, v.stage.help_duel]) expect(s?.trim()).toBeTruthy();
  });
  it("keeps German umlauts and the deck's own name", () => {
    expect(de.verse.deck.engineering_about).toContain("Reaktorschacht");
    // Real umlauts, never "ue" spellings.
    const umlauts = [0xe4, 0xf6, 0xfc, 0xdf].map((c) => String.fromCharCode(c));
    expect(umlauts.some((u) => de.verse.stage.help_duel.includes(u))).toBe(true);
    expect(en.verse.tools.duel_hint).toContain("Reactor Shaft");
  });
});
